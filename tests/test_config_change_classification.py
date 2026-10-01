"""Regression tests for config-file changes in test classification (#71).

A change to a project/dependency configuration file (``pyproject.toml``,
``package.json``, ``Cargo.toml``, ``go.mod``, ...) can break any test in the
repository, not just tests that share a name with the changed file. The
rule-based fallback used to recommend at most the first ten unmatched tests,
and it took that narrow path even when a config change had produced a direct
match for one test.

These tests pin the corrected behaviour: when a config file changes, every
known test is recommended, and directly changed / source-matched tests stay
``REQUIRED``.
"""

from __future__ import annotations

from ci_test_gate.context import AnalysisContext
from ci_test_gate.context_builder import is_config_file
from ci_test_gate.llm import _fallback_classify
from ci_test_gate.models import Diff, DiffFile, Language, TestRisk

MANY_TESTS = [f"tests/test_mod{i:02d}.py" for i in range(15)]

CONFIG_FILES = [
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "composer.json",
    "requirements.txt",
    "subproject/pyproject.toml",
    "services/api/package.json",
]


def _ctx(paths: list[str], test_files: list[str]) -> AnalysisContext:
    diff = Diff(
        files=[DiffFile(path=p, additions=1, deletions=0) for p in paths],
    )
    return AnalysisContext(
        diff=diff,
        language=Language.PYTHON,
        file_contexts=[],
        test_files_in_repo=list(test_files),
    )


def _by_path(result):
    return {r.suite.path: r.risk for r in result.recommendations}


class TestConfigChangeRecommendsAllTests:
    """A config-file-only change must recommend every known test."""

    def test_more_than_ten_tests_are_recommended(self):
        # Regression: the broad-set branch capped recommendations at 10.
        result = _fallback_classify(_ctx(["pyproject.toml"], MANY_TESTS))
        assert set(_by_path(result)) == set(MANY_TESTS)

    def test_config_change_does_not_hit_the_broad_set_reason(self):
        result = _fallback_classify(_ctx(["pyproject.toml"], MANY_TESTS))
        reasons = {r.reason for r in result.recommendations}
        assert not any("running broad set" in r for r in reasons)

    def test_every_config_filename_is_detected(self):
        for config_file in CONFIG_FILES:
            result = _fallback_classify(_ctx([config_file], MANY_TESTS))
            assert set(_by_path(result)) == set(MANY_TESTS), (
                f"config file not detected: {config_file}"
            )

    def test_recommendation_is_not_required(self):
        result = _fallback_classify(_ctx(["pyproject.toml"], MANY_TESTS))
        assert all(
            r.risk is TestRisk.RECOMMENDED for r in result.recommendations
        )


class TestDirectMatchesSurviveConfigChange:
    """Config changes widen coverage without demoting what we already know."""

    def test_directly_changed_test_stays_required(self):
        result = _fallback_classify(
            _ctx(["pyproject.toml", "tests/test_mod00.py"], MANY_TESTS)
        )
        risks = _by_path(result)
        assert risks["tests/test_mod00.py"] is TestRisk.REQUIRED
        # and the rest are still covered
        assert set(risks) == set(MANY_TESTS)

    def test_source_matched_test_stays_required(self):
        result = _fallback_classify(
            _ctx(["pyproject.toml", "src/mod01.py"], MANY_TESTS)
        )
        risks = _by_path(result)
        assert risks["tests/test_mod01.py"] is TestRisk.REQUIRED
        assert set(risks) == set(MANY_TESTS)

    def test_no_duplicate_recommendations(self):
        result = _fallback_classify(
            _ctx(["pyproject.toml", "src/mod01.py", "tests/test_mod00.py"], MANY_TESTS)
        )
        paths = [r.suite.path for r in result.recommendations]
        assert len(paths) == len(set(paths))


class TestNonConfigChangesUnaffected:
    """The fix must not widen behaviour for ordinary source changes."""

    def test_source_change_without_config_keeps_narrow_behavior(self):
        result = _fallback_classify(_ctx(["src/mod01.py"], MANY_TESTS))
        risks = _by_path(result)
        assert set(risks) == {"tests/test_mod01.py"}
        assert risks["tests/test_mod01.py"] is TestRisk.REQUIRED

    def test_unrelated_change_keeps_broad_set_cap(self):
        result = _fallback_classify(_ctx(["src/unrelated.py"], MANY_TESTS))
        assert len(result.recommendations) == 10

    def test_normal_mode_restores_previous_behavior(self):
        result = _fallback_classify(
            _ctx(["pyproject.toml"], MANY_TESTS), config_changes="normal"
        )
        assert len(result.recommendations) == 10

    def test_normal_mode_with_direct_match(self):
        result = _fallback_classify(
            _ctx(["pyproject.toml", "src/mod01.py"], MANY_TESTS),
            config_changes="normal",
        )
        assert set(_by_path(result)) == {"tests/test_mod01.py"}


class TestDocAndCIOnlyStillNarrow:
    """Documentation and workflow edits are not dependency changes."""

    def test_readme_change_keeps_broad_set_cap(self):
        result = _fallback_classify(_ctx(["README.md"], MANY_TESTS))
        assert len(result.recommendations) == 10

    def test_workflow_change_keeps_broad_set_cap(self):
        result = _fallback_classify(_ctx([".github/workflows/ci.yml"], MANY_TESTS))
        assert len(result.recommendations) == 10


class TestIsConfigFile:
    """Unit coverage for the shared detection helper."""

    def test_detects_basenames(self):
        for name in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod"):
            assert is_config_file(name) is True

    def test_detects_in_subprojects(self):
        assert is_config_file("services/api/package.json") is True
        assert is_config_file("subproject/pyproject.toml") is True

    def test_case_insensitive(self):
        assert is_config_file("CARGO.TOML") is True

    def test_backslash_paths(self):
        assert is_config_file("src\\pkg\\package.json") is True

    def test_rejects_non_config(self):
        for path in ("README.md", "src/main.py", ".github/workflows/ci.yml"):
            assert is_config_file(path) is False

    def test_rejects_empty(self):
        assert is_config_file("") is False
        assert is_config_file("/") is False


class TestConfigChangeWithoutTestFiles:
    """A repo with no discoverable tests must not crash."""

    def test_no_test_files(self):
        result = _fallback_classify(_ctx(["pyproject.toml"], []))
        assert result.recommendations == []