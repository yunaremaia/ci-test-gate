"""LLM-powered test classifier — recommends which tests to run."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .context_builder import ChangeContext
from .diff_parser import DiffParser, FileChange

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

    def __init__(self, classifier_type: str = "heuristic"):
        self.classifier_type = classifier_type

    @classmethod
    def from_config(cls, config):
        if config.get("classifier_type") == "llm":
            return LLMTestClassifier(config)
        elif config.get("classifier_type") == "heuristic":
            return HeuristicTestClassifier(config)
        else:
            raise ValueError("Invalid classifier type")

    def classify(self, changes: list, context: ChangeContext, test_files: list[str] | None = None) -> TestRecommendation:
        if self.classifier_type == "llm":
            return self.llm_classify(changes, context)
        elif self.classifier_type == "heuristic":
            return self.heuristic_classify(changes, context, test_files)
        else:
            raise ValueError("Invalid classifier type")

    def llm_classify(self, changes: list, context: ChangeContext) -> TestRecommendation:
        # Implement LLM-based classification logic
        return TestRecommendation(
            reasoning="LLM classifier not yet implemented; falling back to heuristic.",
        )

    def heuristic_classify(
        self,
        changes: list,
        context: ChangeContext,
        test_files: list[str] | None = None,
    ) -> TestRecommendation:
        """Simple heuristic: recommend tests matching changed file paths."""
        required: list[str] = []
        recommended: list[str] = []
        for change in changes:
            path = change.path
            if test_files:
                for tf in test_files:
                    if path in tf or tf.replace("test_", "").replace("_test.", ".") in path:
                        if tf not in required:
                            required.append(tf)
        # If changed files are only CI/workflow, nothing is required
        if not required:
            changed_paths = [c.path for c in changes]
            if all(p.startswith(".github/") or p.endswith(".yml") or p.endswith(".yaml") for p in changed_paths):
                return TestRecommendation(
                    optional=test_files or [],
                    reasoning="CI-only changes detected; no specific tests required.",
                    estimated_savings_pct=80 if test_files else 0,
                )
        return TestRecommendation(
            required=required,
            recommended=recommended,
            reasoning=f"Heuristic match: {len(required)} required test(s) from {len(changes)} changed file(s).",
            estimated_savings_pct=50 if test_files else 0,
        )