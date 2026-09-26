"""LLM-powered test classifier — recommends which tests to run."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .context_builder import ChangeContext
from .diff_parser import DiffParser, FileChange
from .llm import LLMConfig, _is_project_config_path

# Module-level placeholder so tests can patch OpenAI without triggering a
# hard import at import time (the openai package is optional at runtime).
try:
    from openai import OpenAI
except ImportError:  # pragma: no cover — guarded at runtime
    OpenAI = None

@dataclass
class TestRecommendation:
    """Recommendation of which tests to run."""
    required: list[str] = field(default_factory=list)
    recommended: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)
    reasoning: str = ""
    estimated_savings_pct: int = 0

    def to_json(self) -> str:
        return json.dumps({
            "required": self.required,
            "recommended": self.recommended,
            "optional": self.optional,
            "reasoning": self.reasoning,
            "estimated_savings_pct": self.estimated_savings_pct,
        }, indent=2)

    def to_markdown(self) -> str:
        lines = ["## ci-test-gate Recommendation", ""]
        if self.reasoning:
            lines.append(f"**Reasoning:** {self.reasoning}")
            lines.append("")
        if self.required:
            lines.append("### Required (must run)")
            for t in self.required:
                lines.append(f"- {t}")
            lines.append("")
        if self.recommended:
            lines.append("### Recommended")
            for t in self.recommended:
                lines.append(f"- {t}")
            lines.append("")
        if self.optional:
            lines.append("### Optional (can skip)")
            for t in self.optional:
                lines.append(f"- {t}")
            lines.append("")
        if self.estimated_savings_pct:
            lines.append(f"**Estimated CI time savings:** {self.estimated_savings_pct}%")
        return "\n".join(lines)

class TestClassifier:
    """Classify tests based on code changes."""

    def __init__(self, classifier_type: str = "heuristic", config: dict | None = None):
        self.classifier_type = classifier_type
        self.config = config or {}

    @classmethod
    def from_config(cls, config):
        if config.get("classifier_type") == "llm":
            return LLMTestClassifier(config)
        elif config.get("classifier_type") == "heuristic":
            return HeuristicTestClassifier(config)
        else:
            raise ValueError("Invalid classifier type")

    def classify(self, changes: list, context: ChangeContext, test_files: list[str] | None = None) -> TestRecommendation:
        text_changes = [c for c in changes if not getattr(c, "is_binary", False)]
        if changes and not text_changes:
            return TestRecommendation(
                optional=test_files or [],
                reasoning="Binary-only changes; no source files to classify.",
            )
        changes = text_changes
        if self.config.get("config_changes", "broad") == "broad" and any(
            _is_project_config_path(change.path) for change in changes
        ):
            return self.heuristic_classify(changes, context, test_files)
        if self.classifier_type == "llm":
            return self.llm_classify(changes, context, test_files)
        elif self.classifier_type == "heuristic":
            return self.heuristic_classify(changes, context, test_files)
        else:
            raise ValueError("Invalid classifier type")

    def llm_classify(self, changes: list, context: ChangeContext, test_files: list[str] | None = None) -> TestRecommendation:
        """Base implementation: delegates to heuristic. Override in LLMTestClassifier."""
        return self.heuristic_classify(changes, context, test_files)

    def _estimate_savings(self, required: list[str], all_tests: list[str]) -> int:
        """Estimate CI time savings percentage."""
        if not all_tests:
            return 0
        pct = int((1 - len(required) / len(all_tests)) * 100)
        return max(0, min(pct, 95))

    def heuristic_classify(self, changes: list, context: ChangeContext, test_files: list[str] | None = None) -> TestRecommendation:
        """Simple heuristic: recommend tests matching changed file paths."""
        if self.config.get("config_changes", "broad") == "broad" and any(
            _is_project_config_path(change.path) for change in changes
        ):
            all_tests = list(dict.fromkeys(test_files or []))
            non_config_changes = [
                change for change in changes if not _is_project_config_path(change.path)
            ]
            direct_matches = self.heuristic_classify(
                non_config_changes, context, all_tests
            ).required
            required = set(direct_matches) | (
                {change.path for change in changes} & set(all_tests)
            )
            return TestRecommendation(
                required=[test for test in all_tests if test in required],
                recommended=[test for test in all_tests if test not in required],
                reasoning="Project configuration changed; recommend every available test.",
            )
        required: list[str] = []
        optional: list[str] = []
        for change in changes:
            path = change.path
            if test_files:
                for tf in test_files:
                    # Extract base name from test file (strip test_ prefix, _test. suffix, tests/ dir)
                    tf_base = tf.replace("test_", "").replace("_test.", ".").replace("tests/", "")
                    if path in tf or tf_base in path:
                        if tf not in required:
                            required.append(tf)
                    else:
                        if tf not in optional:
                            optional.append(tf)
        # If changed files are only CI/workflow or docs, nothing is required
        if not required:
            changed_paths = [c.path for c in changes]
            is_ci_only = all(p.startswith(".github/") or p.endswith(".yml") or p.endswith(".yaml") for p in changed_paths)
            is_doc_only = all(p.endswith(".md") or p.endswith(".txt") or p.endswith(".rst") for p in changed_paths)
            if is_ci_only or is_doc_only:
                return TestRecommendation(
                    optional=test_files or [],
                    reasoning="CI-only changes detected; no specific tests required." if is_ci_only else "Doc-only changes detected; no specific tests required.",
                    estimated_savings_pct=80 if test_files else 0,
                )
        return TestRecommendation(
            required=required,
            optional=optional,
            reasoning=f"Heuristic match: {len(required)} required test(s) from {len(changes)} changed file(s).",
            estimated_savings_pct=50 if test_files else 0,
        )

class HeuristicTestClassifier(TestClassifier):
    """Heuristic-based test classifier."""

    def __init__(self, config: dict | None = None):
        super().__init__(classifier_type="heuristic", config=config)

class LLMTestClassifier(TestClassifier):
    """LLM-powered test classifier.

    Configuration is read from ``config`` dict or environment variables:

    * ``api_key`` / ``OPENAI_API_KEY``    — OpenAI-compatible API key (required).
    * ``model`` / ``CI_TEST_GATE_MODEL``  — Model name (default: ``gpt-4o-mini``).
    * ``base_url`` / ``OPENAI_BASE_URL``  — Base URL (default: OpenAI production).
    """

    def __init__(self, config: dict | None = None):
        super().__init__(classifier_type="llm", config=config)
        cfg = self.config
        self.api_key: str = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        self.model: str = cfg.get("model") or os.environ.get("CI_TEST_GATE_MODEL", "gpt-4o-mini")
        self.base_url: str = cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def llm_classify(
        self,
        changes: list,
        context: ChangeContext,
        test_files: list[str] | None = None,
    ) -> TestRecommendation:
        """Classify tests using LLM semantic analysis.

        Falls back to the heuristic classifier when no API key is configured
        or when the LLM call fails for any reason.
        """
        if not self.api_key:
            # No API key configured — degrade gracefully.
            return self.heuristic_classify(changes, context, test_files)

        llm_cfg = LLMConfig(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
        )

        system_prompt = (
            "You are an expert CI test classifier. Given a list of changed source files "
            "and available test files, classify each test as 'required', 'recommended', "
            "or 'optional' based on how likely the changes are to cause regressions. "
            "Be conservative — when in doubt mark as 'recommended'.\n\n"
            "Return ONLY a JSON object (no markdown fences) with this exact schema:\n"
            '{"required": [...], "recommended": [...], "optional": [...], '
            '"reasoning": "<one-line summary>", "estimated_savings_pct": <0-95>}'
        )

        changed_paths = [c.path for c in changes]
        user_prompt_parts = [
            "## Changed source files",
            *[f"- {p}" for p in changed_paths],
            "",
        ]
        if test_files:
            user_prompt_parts += [
                f"## Available test files ({len(test_files)})",
                *[f"- {t}" for t in test_files[:200]],
                "",
            ]
        user_prompt = "\n".join(user_prompt_parts)

        try:
            # Use the module-level OpenAI (patched by tests). At import time
            # this is bound to ``openai.OpenAI``; at test time it is a MagicMock.
            client = OpenAI(
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
            )
            response = client.chat.completions.create(
                model=llm_cfg.model,
                temperature=llm_cfg.temperature,
                max_tokens=llm_cfg.max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = (response.choices[0].message.content or "").strip()

            # Strip optional markdown fences some models emit.
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

            data = json.loads(raw)
            return TestRecommendation(
                required=data.get("required", []),
                recommended=data.get("recommended", []),
                optional=data.get("optional", []),
                reasoning=data.get("reasoning", ""),
                estimated_savings_pct=int(data.get("estimated_savings_pct", 0)),
            )
        except Exception as exc:
            # Any failure (network, parse, etc.) → heuristic fallback.
            fallback = self.heuristic_classify(changes, context, test_files)
            fallback.reasoning = (
                f"LLM call failed ({type(exc).__name__}: {exc}); "
                f"heuristic fallback: {fallback.reasoning}"
            )
            return fallback
