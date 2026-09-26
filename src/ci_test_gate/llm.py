"""LLM-based test classifier."""

from __future__ import annotations

import json
import os
import re

from .context import AnalysisContext
from .models import (
    AnalysisResult,
    TestRecommendation,
    TestRisk,
    TestSuite,
)

# System prompt for the LLM
SYSTEM_PROMPT = """You are a test selection expert. Given a code diff and project context, classify which test suites should be run.

Risk levels:
- REQUIRED: Tests that MUST run — high risk of regression if skipped (direct test of changed code, critical path)
- RECOMMENDED: Tests that SHOULD run — medium risk (integration tests touching related modules)
- OPTIONAL: Tests that CAN be skipped — low risk (unrelated modules, pure docs)

Rules:
1. If a source file changed, its direct test file is REQUIRED
2. If a test file changed, that test is REQUIRED
3. Integration/e2e tests are RECOMMENDED if they touch changed modules
4. Pure documentation changes → all tests OPTIONAL
5. Config changes (CI, linting) → all tests OPTIONAL
6. Be conservative: when in doubt, mark as RECOMMENDED

Output JSON only, no markdown:
{
  "recommendations": [
    {
      "path": "path/to/test_file.py",
      "risk": "required|recommended|optional",
      "reason": "brief explanation",
      "confidence": 0.9
    }
  ],
  "estimated_savings_seconds": 120,
  "summary": "one-line summary"
}
"""


class LLMConfig:
    """LLM configuration."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("CI_TEST_GATE_MODEL", "gpt-4o-mini"),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )


def _build_user_prompt(ctx: AnalysisContext) -> str:
    """Build the user prompt for the LLM."""
    parts = [
        "## Project Context",
        f"Language: {ctx.language.value}",
        f"Test framework: {ctx.test_framework}",
        "",
        "## Diff",
    ]

    for f in ctx.diff.files:
        parts.append(f"\n### {f.path} (+{f.additions}/-{f.deletions})")
        for hunk in f.hunks[:3]:
            parts.append("```")
            parts.append(hunk[:500])
            parts.append("```")

    if ctx.test_files_in_repo:
        parts.append(f"\n## Available Test Files ({len(ctx.test_files_in_repo)})")
        for t in ctx.test_files_in_repo[:100]:
            parts.append(f"- {t}")
        if len(ctx.test_files_in_repo) > 100:
            parts.append(f"... and {len(ctx.test_files_in_repo) - 100} more")

    return "\n".join(parts)


def _normalize_name(value: str) -> str:
    """Normalize a filename or module name so naming conventions align."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _source_variants(source_path: str) -> set[str]:
    """Return likely names for a source file, including nested module names."""
    normalized = source_path.replace("\\", "/").strip("/")
    name_no_ext = normalized.rsplit(".", 1)[0] if "." in os.path.basename(normalized) else normalized
    segments = [seg for seg in name_no_ext.split("/") if seg]
    variants: set[str] = set()

    if not segments:
        return variants

    variants.add(_normalize_name(os.path.basename(name_no_ext)))
    if len(segments) > 1:
        variants.add(_normalize_name("_".join(segments[-2:])))
    if len(segments) > 2:
        variants.add(_normalize_name("_".join(segments[-3:])))

    return {variant for variant in variants if variant}


def _test_variants(test_path: str) -> set[str]:
    """Return likely underlying names for a test file, removing known prefixes/suffixes."""
    base = os.path.basename(test_path)
    stem = os.path.splitext(base)[0]
    value = _normalize_name(stem)
    variants = {value}

    for prefix in ("test_", "spec_", "it_"):
        if value.startswith(prefix):
            variants.add(value[len(prefix):])

    for suffix in ("_test", "_spec"):
        if value.endswith(suffix):
            variants.add(value[: -len(suffix)])

    return {variant for variant in variants if variant}


def _find_test_candidates(source_path: str, test_files: list[str]) -> list[str]:
    """Find test files that likely cover a source file."""
    source_variants = _source_variants(source_path)
    if not source_variants:
        return []

    candidates = []
    seen: set[str] = set()

    for test_path in test_files:
        for variant in _test_variants(test_path):
            if variant in source_variants:
                if test_path not in seen:
                    candidates.append(test_path)
                    seen.add(test_path)
                break

    return candidates[:5]


_PROJECT_CONFIG_FILES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
})


def _is_project_config_path(path: str) -> bool:
    """Match a project-wide configuration file, including in a subproject."""
    return path.replace("\\", "/").rsplit("/", 1)[-1] in _PROJECT_CONFIG_FILES


def _fallback_classify(ctx: AnalysisContext) -> AnalysisResult:
    """Fallback rule-based classification when LLM is unavailable."""
    recommendations: list[TestRecommendation] = []
    config_changed = any(_is_project_config_path(f.path) for f in ctx.diff.files)

    for f in ctx.diff.files:
        path = f.path
        is_test = ctx.diff._is_test_path(path)

        if is_test:
            recommendations.append(TestRecommendation(
                suite=TestSuite(path=path, framework=ctx.test_framework),
                risk=TestRisk.REQUIRED,
                reason="Test file was modified directly",
                confidence=1.0,
            ))
        else:
            # Try to find corresponding test file
            test_candidates = _find_test_candidates(path, ctx.test_files_in_repo)
            for candidate in test_candidates:
                recommendations.append(TestRecommendation(
                    suite=TestSuite(path=candidate, framework=ctx.test_framework),
                    risk=TestRisk.REQUIRED,
                    reason=f"Direct test for modified source {path}",
                    confidence=0.9,
                ))

    # Project configuration can affect every test, even if a direct source
    # match was found. Preserve directly modified tests as REQUIRED.
    if config_changed:
        covered = {rec.suite.path for rec in recommendations}
        for test_path in ctx.test_files_in_repo:
            if test_path not in covered:
                recommendations.append(TestRecommendation(
                    suite=TestSuite(path=test_path, framework=ctx.test_framework),
                    risk=TestRisk.RECOMMENDED,
                    reason="Project configuration changed",
                    confidence=0.8,
                ))
                covered.add(test_path)

    # If no specific tests found, recommend a broad sample.
    if not recommendations and ctx.test_files_in_repo:
        for t in ctx.test_files_in_repo[:10]:
            recommendations.append(TestRecommendation(
                suite=TestSuite(path=t, framework=ctx.test_framework),
                risk=TestRisk.RECOMMENDED,
                reason="No specific match found; running broad set",
                confidence=0.5,
            ))

    return AnalysisResult(
        recommendations=recommendations,
        language=ctx.language,
        estimated_savings=0.0,
        summary=f"Rule-based fallback: {len(recommendations)} tests recommended",
    )


def classify_with_llm(ctx: AnalysisContext, config: LLMConfig | None = None) -> AnalysisResult:
    """Classify tests using an LLM."""
    if config is None:
        config = LLMConfig.from_env()

    if not config.api_key:
        return _fallback_classify(ctx)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.api_key, base_url=config.base_url)

        response = client.chat.completions.create(
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(ctx)},
            ],
        )

        content = response.choices[0].message.content
        if not content:
            return _fallback_classify(ctx)

        data = json.loads(content)
        recommendations = []
        for rec in data.get("recommendations", []):
            recommendations.append(TestRecommendation(
                suite=TestSuite(
                    path=rec["path"],
                    framework=ctx.test_framework,
                ),
                risk=TestRisk(rec.get("risk", "recommended")),
                reason=rec.get("reason", ""),
                confidence=float(rec.get("confidence", 0.8)),
            ))

        return AnalysisResult(
            recommendations=recommendations,
            language=ctx.language,
            estimated_savings=float(data.get("estimated_savings_seconds", 0)),
            summary=data.get("summary", "LLM classification complete"),
        )

    except Exception as e:
        # Fallback on any error
        result = _fallback_classify(ctx)
        result.summary = f"LLM failed ({type(e).__name__}); fallback: {result.summary}"
        return result
