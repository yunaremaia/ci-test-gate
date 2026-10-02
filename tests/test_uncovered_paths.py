"""Tests for the remaining uncovered code paths in ci-test-gate.

Each test here exercises a real branch of production code rather than
restating an implementation detail: the goal is a coverage number that
reflects behaviour that is actually verified, so these can be used as the
basis for a coverage gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ci_test_gate.classifier import (
    HeuristicTestClassifier,
    LLMTestClassifier,
    TestClassifier,
    TestRecommendation,
)
from ci_test_gate.context import (
    AnalysisContext,
    build_context,
    detect_language,
    detect_test_framework,
)
from ci_test_gate.context_builder import ChangeContext, ContextBuilder
from ci_test_gate.diff_parser import DiffParser, FileChange
from ci_test_gate.llm import (
    LLMConfig,
    _build_user_prompt,
    _fallback_classify,
    _find_test_candidates,
    _normalize_name,
    _source_variants,
    _test_variants,
    classify_with_llm,
)
from ci_test_gate.models import (
    AnalysisResult,
    Diff,
    DiffFile,
    Language,
    TestRecommendation as ModelTestRecommendation,
    TestRisk,
    TestSuite,
)
from ci_test_gate.parser import parse_from_git, parse_unified_diff


# ---------------------------------------------------------------------------
# parser.py — the git-backed and multi-hunk paths
# ---------------------------------------------------------------------------

MULTI_HUNK_DIFF = textwrap.dedent("""\
    diff --git a/src/app.py b/src/app.py
    index 1111111..2222222 100644
    --- a/src/app.py
    +++ b/src/app.py
    @@ -1,4 +1,5 @@
     import os
    -import sys
    +import sys
    +import json
     # header
    @@ -20,3 +21,4 @@ def existing():
         pass
    -    return 1
    +    return 2
    \\ No newline at end of file
    diff --git a/src/other.py b/src/other.py
    new file mode 100644
    index 0000000..3333333
    --- /dev/null
    +++ b/src/other.py
    @@ -0,0 +1,2 @@
    +created
    +lines
""")


def test_parse_unified_diff_counts_additions_and_deletions_per_file():
    diff = parse_unified_diff(MULTI_HUNK_DIFF)

    by_path = {f.path: f for f in diff.files}
    assert set(by_path) == {"src/app.py", "src/other.py"}
    assert by_path["src/app.py"].additions == 3
    assert by_path["src/app.py"].deletions == 2
    assert by_path["src/other.py"].additions == 2
    assert by_path["src/other.py"].deletions == 0


def test_parse_unified_diff_stores_each_hunk_separately():
    diff = parse_unified_diff(MULTI_HUNK_DIFF)

    app = next(f for f in diff.files if f.path == "src/app.py")
    assert len(app.hunks) == 2
    assert app.hunks[0].startswith("@@ -1,4 +1,5 @@")
    assert app.hunks[1].startswith("@@ -20,3 +21,4 @@")


def test_no_newline_marker_is_not_counted_as_content():
    diff = parse_unified_diff(MULTI_HUNK_DIFF)

    app = next(f for f in diff.files if f.path == "src/app.py")
    assert not any("\\ No newline" in h for h in app.hunks)


def test_hunk_closes_when_a_non_content_line_appears():
    diff = parse_unified_diff(
        textwrap.dedent("""\
            diff --git a/src/app.py b/src/app.py
            index 1111111..2222222 100644
            --- a/src/app.py
            +++ b/src/app.py
            @@ -1,2 +1,2 @@
             keep
            +added
            diff --git a/next.py b/next.py
            index 3333333..4444444 100644
            --- a/next.py
            +++ b/next.py
            @@ -1 +1 @@
            -old
            +new
        """)
    )

    assert [f.path for f in diff.files] == ["src/app.py", "next.py"]
    assert len(diff.files[0].hunks) == 1


def test_hunk_closes_when_a_line_falls_outside_every_prefix():
    """A bare line with no +/-/space/\\ prefix ends the open hunk.

    `parse_unified_diff` treats any unrecognised line as the end of a hunk,
    which is how it recovers when a diff carries metadata (an ``index`` line,
    for instance) between hunks.
    """
    diff = parse_unified_diff(
        textwrap.dedent("""\
            diff --git a/src/app.py b/src/app.py
            index 1111111..2222222 100644
            --- a/src/app.py
            +++ b/src/app.py
            @@ -1,2 +1,3 @@
             keep
            +added
            index 1111111..2222222 100644
            @@ -9,1 +9,1 @@
            -old
            +new
        """)
    )

    app = diff.files[0]
    assert len(app.hunks) == 2
    assert app.hunks[0].endswith("+added")
    assert app.additions == 2


def test_a_trailing_hunk_is_still_recorded_when_the_diff_ends():
    diff = parse_unified_diff(
        textwrap.dedent("""\
            diff --git a/src/app.py b/src/app.py
            index 1111111..2222222 100644
            --- a/src/app.py
            +++ b/src/app.py
            @@ -1,1 +1,2 @@
             keep
            +added
        """)
    )

    app = diff.files[0]
    # textwrap.dedent leaves a trailing newline, so the recorded hunk keeps
    # that empty final line rather than ending at "+added".
    assert app.hunks[-1].split("\n")[0] == "@@ -1,1 +1,2 @@"
    assert "+added" in app.hunks[-1]


def test_blank_lines_inside_a_hunk_are_kept():
    diff = parse_unified_diff(
        textwrap.dedent("""\
            diff --git a/src/app.py b/src/app.py
            index 1111111..2222222 100644
            --- a/src/app.py
            +++ b/src/app.py
            @@ -1,1 +1,3 @@
             keep
            +added
            +
            +more
        """)
    )

    # The hunk keeps raw lines verbatim: the bare "+" is not rewritten to "".
    assert diff.files[0].hunks[-1].split("\n") == [
        "@@ -1,1 +1,3 @@",
        " keep",
        "+added",
        "+",
        "+more",
        "",
    ]


def test_parse_unified_diff_preserves_the_raw_input():
    diff = parse_unified_diff(MULTI_HUNK_DIFF)

    assert diff.raw == MULTI_HUNK_DIFF


def test_parse_from_git_reads_a_real_repository(tmp_path, monkeypatch):
    """`parse_from_git` shells out to git in the process CWD, so chdir first."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(tmp_path),
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-b", "main")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def app():\n    return 1\n")
    git("add", ".")
    git("commit", "-m", "base")

    # The change has to live on a branch: `parse_from_git` diffs
    # `base...head`, and `main...HEAD` is empty while HEAD *is* main.
    git("checkout", "-b", "feature")
    (repo / "src" / "app.py").write_text("def app():\n    return 2\n")
    git("add", ".")
    git("commit", "-m", "change")

    monkeypatch.chdir(repo)
    diff = parse_from_git("main", "HEAD")

    assert [f.path for f in diff.files] == ["src/app.py"]
    assert diff.files[0].additions == 1
    assert diff.files[0].deletions == 1


def test_parse_from_git_raises_a_runtime_error_on_a_bad_revision(tmp_path):
    with pytest.raises(RuntimeError, match="git diff failed"):
        parse_from_git("no-such-branch-xyz", "HEAD")


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------


def test_summary_truncates_the_test_file_list_after_fifty():
    ctx = AnalysisContext(
        diff=Diff(),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[f"tests/test_{i}.py" for i in range(60)],
        test_framework="pytest",
    )

    summary = ctx.summary

    assert "Available test files (60)" in summary
    assert "... and 10 more" in summary
    assert "tests/test_59.py" not in summary


def test_summary_lists_every_test_file_when_under_the_cap():
    ctx = AnalysisContext(
        diff=Diff(),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[f"tests/test_{i}.py" for i in range(5)],
        test_framework="pytest",
    )

    assert "... and" not in ctx.summary
    assert "tests/test_4.py" in ctx.summary


def test_summary_omits_the_test_section_when_there_are_none():
    ctx = AnalysisContext(
        diff=Diff(), language=Language.PYTHON, file_contexts=[], test_files_in_repo=[]
    )

    assert "Available test files" not in ctx.summary


def test_build_context_extracts_python_definitions_as_exports():
    diff = Diff(
        files=[
            DiffFile(
                path="src/app.py",
                additions=2,
                hunks=["@@ -1,2 +1,2 @@\nimport os\ndef handler(request):"],
            )
        ]
    )

    ctx = build_context(diff, repo_root=".")

    file_ctx = ctx.file_contexts[0]
    assert file_ctx.path == "src/app.py"
    assert file_ctx.imports == ["import os"]
    assert file_ctx.exports == ["def handler"]


def test_build_context_extracts_javascript_exports():
    diff = Diff(
        files=[
            DiffFile(
                path="src/app.js",
                hunks=["@@ -1,2 +1,2 @@\nimport fs from 'fs'\nexport function handler() {"],
            )
        ]
    )

    ctx = build_context(diff, repo_root=".")

    file_ctx = ctx.file_contexts[0]
    assert file_ctx.imports == ["import fs from 'fs'"]
    # `line.split("(")[0].split(" ")[-1]` keeps the bare symbol, not the keyword.
    assert file_ctx.exports == ["handler"]


def test_detect_language_of_an_empty_diff_is_unknown():
    assert detect_language(Diff()) == Language.UNKNOWN


def test_detect_test_framework_defaults_to_unknown_for_an_unmapped_language():
    assert detect_test_framework(Language.UNKNOWN) == "unknown"


# ---------------------------------------------------------------------------
# llm.py helpers
# ---------------------------------------------------------------------------


def test_normalize_name_collapses_separators_to_underscores():
    assert _normalize_name("My Module-Name.py") == "my_module_name_py"
    assert _normalize_name("__leading__") == "leading"


def test_source_variants_include_nested_module_names():
    variants = _source_variants("pkg/sub/mod.py")

    assert "mod" in variants
    assert "sub_mod" in variants
    assert "pkg_sub_mod" in variants


def test_source_variants_are_empty_for_a_path_with_no_name():
    assert _source_variants("/") == set()


def test_source_variants_handle_a_directory_style_dotfile():
    assert "mod" in _source_variants("mod.py")


def test_test_variants_strip_known_prefixes_and_suffixes():
    assert _test_variants("tests/test_thing.py") == {"test_thing", "thing"}
    assert "thing" in _test_variants("spec/thing.spec.ts")
    assert "thing" in _test_variants("src/thing_test.go")


def test_find_test_candidates_returns_nothing_for_a_sourceless_path():
    assert _find_test_candidates("/", ["tests/test_thing.py"]) == []


def test_find_test_candidates_caps_results_at_five():
    # `_test_variants` works on the basename, so every file below yields the
    # bare variant "mod", which is a variant of src/mod.py. Six matches for a
    # five-slot cap is what makes this assert the truncation.
    test_files = [
        "tests/test_mod.py",
        "unit/mod_test.py",
        "other/mod_test.py",
        "more/mod_test.py",
        "extra/mod_test.py",
        "deep/mod_test.py",
    ]

    candidates = _find_test_candidates("src/mod.py", test_files)

    assert len(candidates) == 5
    assert candidates == test_files[:5]


def test_find_test_candidates_reports_each_matching_file_once():
    candidates = _find_test_candidates(
        "src/thing.py", ["tests/test_thing.py", "tests/thing_test.py"]
    )

    # Both files match via a different variant; each is reported once.
    assert candidates == ["tests/test_thing.py", "tests/thing_test.py"]


def test_build_user_prompt_includes_hunks_for_each_file():
    ctx = AnalysisContext(
        diff=Diff(
            files=[
                DiffFile(path="src/a.py", additions=1, deletions=0, hunks=["@@ -1 +1 @@\n+x"]),
                DiffFile(path="src/b.py", additions=1, deletions=0, hunks=["@@ -5 +5 @@\n+y"]),
            ]
        ),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[],
        test_framework="pytest",
    )

    prompt = _build_user_prompt(ctx)

    assert "### src/a.py (+1/-0)" in prompt
    assert "### src/b.py (+1/-0)" in prompt
    assert prompt.count("```") == 4


def test_build_user_prompt_limits_each_file_to_three_hunks():
    hunks = [f"@@ -{i} +{i} @@\n+line{i}" for i in range(1, 6)]
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="src/a.py", hunks=hunks)]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[],
    )

    prompt = _build_user_prompt(ctx)

    assert "+line5" not in prompt
    assert prompt.count("```") == 6


def test_build_user_prompt_truncates_the_test_file_list_after_one_hundred():
    ctx = AnalysisContext(
        diff=Diff(),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[f"tests/test_{i}.py" for i in range(130)],
    )

    prompt = _build_user_prompt(ctx)

    assert "## Available Test Files (130)" in prompt
    assert "... and 30 more" in prompt


def test_fallback_classify_marks_a_config_change_and_returns_early():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="pyproject.toml")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_a.py", "tests/test_b.py"],
    )

    result = _fallback_classify(ctx, config_changes="broad")

    assert {r.suite.path for r in result.recommendations} == {
        "tests/test_a.py",
        "tests/test_b.py",
    }
    assert all(r.risk == TestRisk.RECOMMENDED for r in result.recommendations)
    assert "config change" in result.summary


def test_fallback_classify_ignores_a_config_change_in_normal_mode():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="pyproject.toml")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_a.py", "tests/test_b.py"],
    )

    result = _fallback_classify(ctx, config_changes="normal")

    assert {r.suite.path for r in result.recommendations} == {
        "tests/test_a.py",
        "tests/test_b.py",
    }
    assert all(r.risk == TestRisk.RECOMMENDED for r in result.recommendations)
    assert "config change" not in result.summary


def test_fallback_classify_caps_the_broad_set_at_ten():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="README.md")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[f"tests/test_{i}.py" for i in range(25)],
    )

    result = _fallback_classify(ctx, config_changes="normal")

    assert len(result.recommendations) == 10
    assert all(r.reason == "No specific match found; running broad set" for r in result.recommendations)


def test_fallback_classify_keeps_a_directly_changed_test_required():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="tests/test_a.py")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_a.py", "tests/test_b.py"],
    )

    result = _fallback_classify(ctx)

    by_path = {r.suite.path: r for r in result.recommendations}
    assert by_path["tests/test_a.py"].risk == TestRisk.REQUIRED
    assert by_path["tests/test_a.py"].confidence == 1.0
    assert by_path["tests/test_a.py"].reason == "Test file was modified directly"


def test_fallback_classify_matches_a_source_to_its_test():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="src/app.py")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_app.py"],
    )

    result = _fallback_classify(ctx)

    assert [r.suite.path for r in result.recommendations] == ["tests/test_app.py"]
    assert result.recommendations[0].risk == TestRisk.REQUIRED
    assert result.recommendations[0].reason == "Direct test for modified source src/app.py"


def test_classify_with_llm_uses_the_environment_when_no_config_is_passed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="tests/test_a.py")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_a.py"],
    )

    result = classify_with_llm(ctx)

    assert result.recommendations[0].risk == TestRisk.REQUIRED


def test_classify_with_llm_falls_back_when_the_llm_raises(monkeypatch):
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="tests/test_a.py")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_a.py"],
    )

    with patch("ci_test_gate.llm.OpenAI", create=True):
        with patch.dict(sys.modules, {"openai": MagicMock(OpenAI=MagicMock(side_effect=RuntimeError("boom")))}):
            result = classify_with_llm(ctx, LLMConfig(api_key="sk-test"))

    assert result.summary.startswith("LLM failed (RuntimeError); fallback:")


def test_classify_with_llm_falls_back_on_an_empty_completion():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="tests/test_a.py")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=["tests/test_a.py"],
    )

    choice = MagicMock()
    choice.message.content = None
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response

    with patch.dict(sys.modules, {"openai": MagicMock(OpenAI=MagicMock(return_value=client))}):
        result = classify_with_llm(ctx, LLMConfig(api_key="sk-test"))

    assert "Rule-based fallback" in result.summary


def test_classify_with_llm_maps_a_successful_response():
    ctx = AnalysisContext(
        diff=Diff(files=[DiffFile(path="src/app.py")]),
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=[],
        test_framework="pytest",
    )
    payload = json.dumps(
        {
            "recommendations": [
                {"path": "tests/test_app.py", "risk": "required", "reason": "direct", "confidence": 0.9},
                {"path": "tests/test_other.py", "reason": "maybe"},
            ],
            "estimated_savings_seconds": 42,
            "summary": "done",
        }
    )
    choice = MagicMock()
    choice.message.content = payload
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response

    with patch.dict(sys.modules, {"openai": MagicMock(OpenAI=MagicMock(return_value=client))}):
        result = classify_with_llm(ctx, LLMConfig(api_key="sk-test"))

    assert [r.suite.path for r in result.recommendations] == [
        "tests/test_app.py",
        "tests/test_other.py",
    ]
    assert result.recommendations[0].risk == TestRisk.REQUIRED
    assert result.recommendations[1].risk == TestRisk.RECOMMENDED
    assert result.recommendations[1].confidence == 0.8
    assert result.estimated_savings == 42.0
    assert result.summary == "done"
    assert result.language == Language.PYTHON


def test_llm_config_from_env_reads_every_variable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("CI_TEST_GATE_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")

    cfg = LLMConfig.from_env()

    assert (cfg.api_key, cfg.model, cfg.base_url) == (
        "sk-env",
        "gpt-4o",
        "https://example.invalid/v1",
    )
    assert cfg.temperature == 0.1
    assert cfg.max_tokens == 2048


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


def test_diff_all_paths_lists_every_file():
    diff = Diff(files=[DiffFile(path="a.py"), DiffFile(path="b.py")])

    assert diff.all_paths == ["a.py", "b.py"]


def test_analysis_result_partitions_by_risk():
    result = AnalysisResult(
        recommendations=[
            ModelTestRecommendation(suite=TestSuite(path="a.py"), risk=TestRisk.REQUIRED),
            ModelTestRecommendation(suite=TestSuite(path="b.py"), risk=TestRisk.RECOMMENDED),
            ModelTestRecommendation(suite=TestSuite(path="c.py"), risk=TestRisk.OPTIONAL),
        ]
    )

    assert [r.suite.path for r in result.required] == ["a.py"]
    assert [r.suite.path for r in result.recommended] == ["b.py"]
    assert [r.suite.path for r in result.optional] == ["c.py"]


# ---------------------------------------------------------------------------
# classifier.py
# ---------------------------------------------------------------------------


def test_to_markdown_renders_the_recommended_section():
    rec = TestRecommendation(
        required=["tests/test_a.py"],
        recommended=["tests/test_b.py"],
        reasoning="because",
        estimated_savings_pct=33,
    )

    markdown = rec.to_markdown()

    assert "### Required (must run)" in markdown
    assert "- tests/test_a.py" in markdown
    assert "### Recommended" in markdown
    assert "- tests/test_b.py" in markdown
    assert "**Estimated CI time savings:** 33%" in markdown


def test_to_markdown_omits_the_optional_section_when_empty():
    markdown = TestRecommendation(required=["tests/test_a.py"]).to_markdown()

    assert "### Optional" not in markdown
    assert "**Reasoning:**" not in markdown
    assert "**Estimated CI time savings:**" not in markdown


def test_from_config_builds_the_heuristic_classifier():
    classifier = TestClassifier.from_config({"classifier_type": "heuristic"})

    assert isinstance(classifier, HeuristicTestClassifier)
    assert classifier.config_changes == "broad"


def test_from_config_builds_the_llm_classifier():
    classifier = TestClassifier.from_config(
        {"classifier_type": "llm", "api_key": "sk-test", "model": "gpt-4o"}
    )

    assert isinstance(classifier, LLMTestClassifier)
    assert classifier.model == "gpt-4o"


def test_from_config_rejects_an_unknown_classifier_type():
    with pytest.raises(ValueError, match="Invalid classifier type"):
        TestClassifier.from_config({"classifier_type": "magic"})


def test_from_config_rejects_a_missing_classifier_type():
    with pytest.raises(ValueError, match="Invalid classifier type"):
        TestClassifier.from_config({})


def test_classify_rejects_an_unknown_classifier_type():
    classifier = TestClassifier(classifier_type="magic")

    with pytest.raises(ValueError, match="Invalid classifier type"):
        classifier.classify([FileChange(path="src/a.py")], ChangeContext(changed_files=[]))


def test_llm_classify_on_the_base_class_delegates_to_the_heuristic():
    classifier = TestClassifier(classifier_type="llm")
    changes = [FileChange(path="tests/test_a.py")]

    result = classifier.llm_classify(changes, ChangeContext(changed_files=[]), ["tests/test_a.py"])

    assert result.required == ["tests/test_a.py"]


def test_estimate_savings_is_zero_without_a_total():
    assert TestClassifier()._estimate_savings(["tests/test_a.py"], []) == 0


def test_estimate_savings_is_capped_at_ninety_five():
    classifier = TestClassifier()
    all_tests = [f"tests/test_{i}.py" for i in range(100)]

    assert classifier._estimate_savings([], all_tests) == 95


def test_heuristic_subclass_sets_its_own_type():
    classifier = HeuristicTestClassifier(config={"config_changes": "normal"})

    assert classifier.classifier_type == "heuristic"
    assert classifier.config_changes == "normal"


def test_llm_classifier_reads_its_defaults_from_the_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CI_TEST_GATE_MODEL", "gpt-4o-mini-env")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    classifier = LLMTestClassifier()

    assert classifier.api_key == ""
    assert classifier.model == "gpt-4o-mini-env"
    assert classifier.base_url == "https://api.openai.com/v1"


def test_llm_classifier_strips_markdown_fences_from_the_response():
    payload = json.dumps({"required": ["tests/test_a.py"], "reasoning": "fenced"})
    choice = MagicMock()
    choice.message.content = f"```json\n{payload}\n```"
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response

    with patch("ci_test_gate.classifier.OpenAI", return_value=client):
        result = LLMTestClassifier({"api_key": "sk-test"}).llm_classify(
            [FileChange(path="src/a.py")], ChangeContext(changed_files=[]), []
        )

    assert result.required == ["tests/test_a.py"]
    assert result.reasoning == "fenced"


def test_llm_classifier_applies_documented_defaults_for_absent_fields():
    choice = MagicMock()
    choice.message.content = json.dumps({"required": ["tests/test_a.py"]})
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response

    with patch("ci_test_gate.classifier.OpenAI", return_value=client):
        result = LLMTestClassifier({"api_key": "sk-test"}).llm_classify(
            [FileChange(path="src/a.py")], ChangeContext(changed_files=[]), []
        )

    assert result.recommended == []
    assert result.optional == []
    assert result.reasoning == ""
    assert result.estimated_savings_pct == 0


def test_llm_classifier_sends_the_test_file_list_in_the_user_prompt():
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = "{}"

    with patch("ci_test_gate.classifier.OpenAI", return_value=client):
        LLMTestClassifier({"api_key": "sk-test"}).llm_classify(
            [FileChange(path="src/a.py")],
            ChangeContext(changed_files=[]),
            ["tests/test_a.py"],
        )

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert "## Available test files (1)" in messages[1]["content"]
    assert "- tests/test_a.py" in messages[1]["content"]


def test_llm_classifier_caps_the_test_file_list_in_the_prompt_at_two_hundred():
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = "{}"
    test_files = [f"tests/test_{i}.py" for i in range(260)]

    with patch("ci_test_gate.classifier.OpenAI", return_value=client):
        LLMTestClassifier({"api_key": "sk-test"}).llm_classify(
            [FileChange(path="src/a.py")], ChangeContext(changed_files=[]), test_files
        )

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert "## Available test files (260)" in messages[1]["content"]
    assert "- tests/test_259.py" not in messages[1]["content"]


def test_llm_classifier_omits_the_test_section_when_no_tests_are_known():
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = "{}"

    with patch("ci_test_gate.classifier.OpenAI", return_value=client):
        LLMTestClassifier({"api_key": "sk-test"}).llm_classify(
            [FileChange(path="src/a.py")], ChangeContext(changed_files=[]), None
        )

    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert "## Available test files" not in messages[1]["content"]


def test_llm_classifier_reports_the_failure_when_falling_back():
    client = MagicMock()
    client.chat.completions.create.side_effect = ValueError("bad json")

    with patch("ci_test_gate.classifier.OpenAI", return_value=client):
        result = LLMTestClassifier({"api_key": "sk-test"}).llm_classify(
            [FileChange(path="src/a.py")], ChangeContext(changed_files=[]), []
        )

    assert result.reasoning.startswith("LLM call failed (ValueError: bad json); heuristic fallback:")
    # The heuristic still produced a real recommendation after the fallback.
    assert "Heuristic match:" in result.reasoning


# ---------------------------------------------------------------------------
# context_builder.py
# ---------------------------------------------------------------------------


def test_prompt_context_lists_removed_imports():
    ctx = ChangeContext(
        changed_files=[FileChange(path="src/a.py")],
        imports_added={"src/a.py": ["os"]},
        imports_removed={"src/a.py": ["sys"]},
        functions_changed={"src/a.py": ["+handler"]},
    )

    prompt = ctx.to_prompt_context()

    assert "Imports added:\n  src/a.py: os" in prompt
    assert "Imports removed:\n  src/a.py: sys" in prompt
    assert "Functions changed:\n  src/a.py: +handler" in prompt


def test_prompt_context_reports_no_test_runners_detected():
    ctx = ChangeContext(changed_files=[FileChange(path="src/a.py")])

    assert "Test runners: none detected" in ctx.to_prompt_context()


def test_prompt_context_lists_detected_test_runners():
    ctx = ChangeContext(changed_files=[], test_runners_detected=["pytest", "jest"])

    assert "Test runners: pytest, jest" in ctx.to_prompt_context()


def test_detect_test_runners_reads_mocha_from_package_json():
    change = FileChange(path="package.json", added_lines=['  "scripts": { "test": "mocha" }'])

    runners = ContextBuilder()._detect_test_runners([change])

    assert "mocha" in runners


def test_detect_test_runners_ignores_package_json_without_a_runner():
    change = FileChange(path="package.json", added_lines=['  "name": "thing"'])

    assert ContextBuilder()._detect_test_runners([change]) == []


def test_detect_test_runners_ignores_pyproject_without_pytest():
    change = FileChange(path="pyproject.toml", added_lines=['[project]', 'name = "thing"'])

    assert ContextBuilder()._detect_test_runners([change]) == []


def test_detect_test_runners_recognises_jest_config_ts():
    change = FileChange(path="jest.config.ts")

    # `filename.startswith("jest.config")` covers both the .js and .ts configs.
    assert ContextBuilder()._detect_test_runners([change]) == ["jest"]


def test_extract_imports_records_removed_imports():
    change = FileChange(
        path="src/a.py",
        added_lines=["import json"],
        removed_lines=["import sys", "from os import path"],
    )
    ctx = ChangeContext(changed_files=[change])

    ContextBuilder()._extract_imports(change, ctx, ".py")

    assert ctx.imports_added == {"src/a.py": ["json"]}
    assert ctx.imports_removed == {"src/a.py": ["sys", "os"]}


def test_extract_functions_records_removed_functions():
    change = FileChange(path="src/a.py", added_lines=[], removed_lines=["def handler():"])
    ctx = ChangeContext(changed_files=[change])

    ContextBuilder()._extract_functions(change, ctx, ".py")

    assert ctx.functions_changed == {"src/a.py": ["-handler"]}


def test_rust_functions_use_the_optional_prefix_group_so_the_fallback_runs():
    """`.rs` is the one language whose group 1 is the optional `pub` prefix.

    For every other pattern group 1 (or 3) is `(\\w+)`, which can never be
    empty. For Rust, group 1 is `(pub\\s+)?` — absent on a plain `fn`, so
    `func_name` is None and the `if not func_name` fallback records the whole
    match. This is the only live path to that branch.
    """
    change = FileChange(path="src/lib.rs", added_lines=["fn plain() {"])
    ctx = ChangeContext(changed_files=[change])

    ContextBuilder()._extract_functions(change, ctx, ".rs")

    assert ctx.functions_changed == {"src/lib.rs": ["+fn plain("]}


def test_rust_functions_use_group_one_when_the_pub_prefix_is_present():
    change = FileChange(path="src/lib.rs", added_lines=["pub fn pubbed() {"])
    ctx = ChangeContext(changed_files=[change])

    ContextBuilder()._extract_functions(change, ctx, ".rs")

    assert ctx.functions_changed == {"src/lib.rs": ["+pub "]}


def test_rust_removed_functions_use_the_fallback_group():
    change = FileChange(path="src/lib.rs", added_lines=[], removed_lines=["fn gone() {"])
    ctx = ChangeContext(changed_files=[change])

    ContextBuilder()._extract_functions(change, ctx, ".rs")

    assert ctx.functions_changed == {"src/lib.rs": ["-fn gone("]}


def test_build_ignores_binary_changes_entirely():
    builder = ContextBuilder()
    binary = FileChange(path="logo.png", added_lines=["import os"], is_binary=True)

    ctx = builder.build([binary])

    assert ctx.changed_files == []
    assert ctx.imports_added == {}
    assert ctx.test_runners_detected == []


def test_build_estimates_large_scope_from_line_count():
    change = FileChange(path="src/a.py", added_lines=[f"line{i}" for i in range(600)])

    assert ContextBuilder().build([change]).estimated_scope == "large"


def test_build_estimates_large_scope_from_file_count():
    changes = [FileChange(path=f"src/a{i}.py") for i in range(25)]

    assert ContextBuilder().build(changes).estimated_scope == "large"


# ---------------------------------------------------------------------------
# diff_parser.py
# ---------------------------------------------------------------------------


def test_get_changed_paths_returns_every_path():
    changes = DiffParser().parse(MULTI_HUNK_DIFF)

    assert DiffParser().get_changed_paths(changes) == ["src/app.py", "src/other.py"]


def test_parse_collects_multiple_hunks_for_one_file():
    changes = DiffParser().parse(MULTI_HUNK_DIFF)

    app = next(c for c in changes if c.path == "src/app.py")
    assert len(app.hunks) == 2


def test_parse_drops_context_lines_from_the_hunk():
    """Context lines are stripped before the `startswith(" ")` check.

    `parse()` compares `raw_line.strip()`, so a diff context line can never
    match and is not recorded in the hunk. This test pins that behaviour:
    it is observable (context lines never reach `added_lines`/`removed_lines`
    either), and it is why the hunk for this fixture holds only the addition.
    """
    changes = DiffParser().parse(MULTI_HUNK_DIFF)

    app = next(c for c in changes if c.path == "src/app.py")
    assert not any("# header" in h for h in app.hunks)
    assert app.added_lines == ["import sys", "import json", "    return 2"]
    assert app.removed_lines == ["import sys", "    return 1"]


def test_get_changed_extensions_skips_files_without_one():
    changes = [FileChange(path="Makefile"), FileChange(path="src/a.py")]

    assert DiffParser().get_changed_extensions(changes) == {".py"}


def test_test_change_helpers_split_on_test_and_non_test_files():
    parser = DiffParser()
    changes = [
        FileChange(path="src/a.py"),
        FileChange(path="tests/test_a.py"),
        FileChange(path="logo.png", is_binary=True),
        FileChange(path="tests/test_bin.py", is_binary=True),
    ]

    assert [c.path for c in parser.get_non_test_changes(changes)] == ["src/a.py"]
    assert [c.path for c in parser.get_test_changes(changes)] == ["tests/test_a.py"]


def test_parse_handles_a_git_binary_patch():
    changes = DiffParser().parse(
        textwrap.dedent("""\
            diff --git a/logo.png b/logo.png
            index 1111111..2222222 100644
            GIT binary patch
            literal 10
            """)
    )

    assert changes[0].is_binary is True
    assert changes[0].added_lines == []


def test_parse_handles_the_no_newline_marker():
    changes = DiffParser().parse(
        textwrap.dedent("""\
            diff --git a/src/a.py b/src/a.py
            index 1111111..2222222 100644
            --- a/src/a.py
            +++ b/src/a.py
            @@ -1 +1 @@
            -old
            \\ No newline at end of file
            +new
            """)
    )

    assert changes[0].added_lines == ["new"]
    assert changes[0].removed_lines == ["old"]