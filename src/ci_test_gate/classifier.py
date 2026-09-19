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

    def __init__(self, classifier_type):
        self.classifier_type = classifier_type

    @classmethod
    def from_config(cls, config):
        if config.get("classifier_type") == "llm":
            return LLMTestClassifier(config)
        elif config.get("classifier_type") == "heuristic":
            return HeuristicTestClassifier(config)
        else:
            raise ValueError("Invalid classifier type")

    def classify(self, context: ChangeContext, diff: DiffParser) -> TestRecommendation:
        if self.classifier_type == "llm":
            return self.llm_classify(context, diff)
        elif self.classifier_type == "heuristic":
            return self.heuristic_classify(context, diff)
        else:
            raise ValueError("Invalid classifier type")

    def llm_classify(self, context: ChangeContext, diff: DiffParser) -> TestRecommendation:
        # Implement LLM-based classification logic
        pass

    def heuristic_classify(self, context: ChangeContext, diff: DiffParser) -> TestRecommendation:
        # Implement heuristic-based classification logic
        pass