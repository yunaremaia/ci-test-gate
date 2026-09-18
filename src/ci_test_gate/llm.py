"""LLM-based test classifier."""

from __future__ import annotations

import json
import os

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


def _find_test_candidates(source_path: str, test_files: list[str]) -> list[str]:
    """Find test files that likely cover a source file."""
    candidates = []
    
    # Normalize path separators
    norm_source = source_path.replace("\\", "/").strip("/")
    source_parts = norm_source.split("/")
    source_file = source_parts[-1]
    
    # Extract base name without extension
    source_base = source_file
    for ext in [".py", ".ts", ".js", ".go", ".rs", ".jsx", ".tsx"]:
        if source_base.endswith(ext):
            source_base = source_base[:-len(ext)]
            break
    else:
        if "." in source_base:
            source_base = source_base.rsplit(".", 1)[0]
            
    # Extract relative path slug excluding common top-level directory names
    trimmed_parts = [p for p in source_parts[:-1] if p not in ("src", "lib", "app", "pkg")]
    path_slug = "_".join(trimmed_parts + [source_base]) if trimmed_parts else source_base

    for test_path in test_files:
        norm_test = test_path.replace("\\", "/").strip("/")
        test_parts = norm_test.split("/")
        test_file = test_parts[-1]
        
        # Strip compound test extensions (.test.ts, .spec.js, _test.go, etc.)
        test_stem = test_file
        for ext in [
            ".test.ts", ".test.js", ".test.jsx", ".test.tsx",
            ".spec.ts", ".spec.js", ".spec.jsx", ".spec.tsx",
            "_test.go", "_test.rs", "_test.py",
            ".py", ".ts", ".js", ".go", ".rs", ".jsx", ".tsx"
        ]:
            if test_stem.endswith(ext):
                test_stem = test_stem[:-len(ext)]
                break
        else:
            if "." in test_stem:
                test_stem = test_stem.rsplit(".", 1)[0]
                
        # 1. Direct match: test_<base>, <base>_test, or stem == base/slug
        if (
            test_stem in (source_base, path_slug)
            or test_stem in (f"test_{source_base}", f"{source_base}_test", f"test_{path_slug}", f"{path_slug}_test")
            or test_stem.startswith(f"test_{path_slug}")
            or test_stem.endswith(f"{path_slug}_test")
            or test_stem.endswith(f"_{source_base}_test")
            or (test_stem == source_base and any(s in norm_test for s in ("test", "spec")))
        ):
            candidates.append(test_path)
            continue

        # 2. Subdirectory match: tests/unit/test_users.py or tests/integration/users_test.py
        if (
            f"test_{source_base}" in test_stem
            or f"{source_base}_test" in test_stem
            or test_stem == source_base
        ):
            candidates.append(test_path)
            continue

    return candidates[:5]


def _fallback_classify(ctx: AnalysisContext) -> AnalysisResult:
    """Fallback rule-based classification when LLM is unavailable."""
    recommendations: list[TestRecommendation] = []

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

    # If no specific tests found, recommend running all
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
