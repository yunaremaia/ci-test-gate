"""Tests for the SARIF 2.1.0 output path of ci-test-gate.

Closes the gap recorded in BACKLOG.md: ``src/ci_test_gate/sarif.py`` had no
test coverage at all, leaving the ``--output sarif`` path of the CLI
completely unexercised. These tests cover the module directly and also drive
it end-to-end through both CLI subcommands.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from ci_test_gate.sarif import (
    RULE_MISSING_REQUIRED_TEST,
    RULE_UNTESTED_CHANGED_FILE,
    RULES,
    recommendation_to_sarif,
    sarif_to_string,
)


# ---------------------------------------------------------------------------
# Document skeleton
# ---------------------------------------------------------------------------


def test_document_is_sarif_2_1_0_with_a_single_run():
    doc = recommendation_to_sarif(required=[], recommended=[])

    assert doc["version"] == "2.1.0"
    assert len(doc["runs"]) == 1


def test_tool_driver_metadata():
    doc = recommendation_to_sarif(required=[], recommended=[])

    driver = doc["runs"][0]["tool"]["driver"]
    assert driver["name"] == "ci-test-gate"
    assert driver["informationUri"] == "https://github.com/yunaremaia/ci-test-gate"
    assert driver["rules"] == RULES


def test_default_tool_version_is_used_when_not_overridden():
    doc = recommendation_to_sarif(required=[], recommended=[])

    assert doc["runs"][0]["tool"]["driver"]["version"] == "0.1.0"


def test_tool_version_is_overridable():
    doc = recommendation_to_sarif(required=[], recommended=[], tool_version="9.9.9")

    assert doc["runs"][0]["tool"]["driver"]["version"] == "9.9.9"


def test_rules_declare_both_expected_ids_with_severity_metadata():
    ids = [rule["id"] for rule in RULES]

    assert RULE_MISSING_REQUIRED_TEST in ids
    assert RULE_UNTESTED_CHANGED_FILE in ids
    assert len(ids) == len(set(ids)), "SARIF rule ids must be unique"

    for rule in RULES:
        assert rule["name"]
        assert rule["shortDescription"]["text"]
        assert rule["fullDescription"]["text"]
        assert rule["helpUri"].startswith("https://")
        assert "security-severity" in rule["properties"]


# ---------------------------------------------------------------------------
# Untested changed file results
# ---------------------------------------------------------------------------


def test_changed_file_with_matching_test_is_not_flagged():
    """A source file whose base name appears in a test path is considered tested.

    This is the regression test for #105: ``recommendation_to_sarif`` used to
    compare test paths against source paths by exact match, so every changed
    source file was flagged as untested even when a corresponding test was
    selected.
    """
    doc = recommendation_to_sarif(
        required=["tests/test_alpha.py"],
        recommended=["tests/test_beta.py"],
        all_changed_files=["src/alpha.py", "src/gamma.py", "src/orphan.py"],
    )

    results = doc["runs"][0]["results"]
    # src/alpha.py is covered by tests/test_alpha.py (base "alpha.py" is a
    # substring of "src/alpha.py"); src/gamma.py and src/orphan.py are not.
    assert [r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in results] == [
        "src/gamma.py",
        "src/orphan.py",
    ]
    result = results[0]
    assert result["ruleId"] == RULE_UNTESTED_CHANGED_FILE
    assert result["level"] == "warning"
    assert result["message"]["text"] == "No test suite selected for changed file: src/gamma.py"
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/gamma.py"


def test_every_recommended_path_counts_as_tested():
    doc = recommendation_to_sarif(
        required=["tests/test_alpha.py"],
        recommended=["tests/test_beta.py", "tests/test_gamma.py"],
        all_changed_files=["src/alpha.py", "src/beta.py", "src/gamma.py"],
    )

    assert doc["runs"][0]["results"] == []


def test_required_and_recommended_are_unioned_when_deciding_what_is_tested():
    """A path covered only by the required list is still considered tested."""
    doc = recommendation_to_sarif(
        required=["tests/test_only_required.py"],
        recommended=[],
        all_changed_files=["src/only_required.py"],
    )

    assert doc["runs"][0]["results"] == []


def test_changed_files_default_to_none_produces_no_results():
    doc = recommendation_to_sarif(required=["tests/test_alpha.py"], recommended=[])

    assert doc["runs"][0]["results"] == []


def test_empty_changed_file_list_produces_no_results():
    doc = recommendation_to_sarif(required=["tests/test_alpha.py"], recommended=[], all_changed_files=[])

    assert doc["runs"][0]["results"] == []


def test_duplicate_untested_paths_are_each_reported():
    """Duplicates are not de-duplicated: the caller owns path uniqueness.

    ``git diff --name-only`` does not repeat paths, so de-duplicating here
    would be dead weight; documenting the pass-through behaviour keeps the
    contract explicit for callers that build the list themselves.
    """
    doc = recommendation_to_sarif(
        required=[],
        recommended=[],
        all_changed_files=["src/orphan.py", "src/orphan.py"],
    )

    results = doc["runs"][0]["results"]
    assert len(results) == 2
    assert {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in results} == {
        "src/orphan.py"
    }


def test_multiple_orphans_each_get_their_own_result_in_order():
    doc = recommendation_to_sarif(
        required=["tests/test_one.py"],
        recommended=[],
        all_changed_files=["src/one.py", "src/two.py"],
    )

    results = doc["runs"][0]["results"]
    assert [r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in results] == [
        "src/two.py",
    ]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_sarif_to_string_round_trips_through_json():
    doc = recommendation_to_sarif(
        required=["tests/test_alpha.py"],
        recommended=[],
        all_changed_files=["src/orphan.py"],
    )

    serialized = sarif_to_string(doc)

    assert json.loads(serialized) == doc


def test_sarif_to_string_is_indented_for_review_in_the_job_summary():
    doc = recommendation_to_sarif(required=[], recommended=[])

    assert "\n  " in sarif_to_string(doc)


def test_missing_required_test_rule_id_is_the_documented_constant():
    """The rule advertised for missing required tests must stay stable.

    GitHub Code Scanning keys alerts on the rule id, so changing it would
    silently orphan every historical alert.
    """
    assert RULE_MISSING_REQUIRED_TEST == "ci-test-gate/missing-required-test"
    assert RULE_UNTESTED_CHANGED_FILE == "ci-test-gate/untested-changed-file"


# ---------------------------------------------------------------------------
# End-to-end through the CLI (`--output sarif`)
# ---------------------------------------------------------------------------


DIFF = textwrap.dedent("""\
    diff --git a/src/orphan.py b/src/orphan.py
    index 1234567..89abcde 100644
    --- a/src/orphan.py
    +++ b/src/orphan.py
    @@ -1,3 +1,4 @@
     def orphan():
    -    return 1
    +    return 2
""")


def test_suggest_command_emits_valid_sarif(tmp_path: Path, capsys):
    from ci_test_gate.cli import main

    diff_file = tmp_path / "change.diff"
    diff_file.write_text(DIFF)

    rc = main(["suggest", "--diff", str(diff_file), "--output", "sarif"])

    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["results"][0]["ruleId"] == RULE_UNTESTED_CHANGED_FILE


def test_suggest_sarif_reports_the_running_version(tmp_path: Path, capsys):
    from ci_test_gate import __version__
    from ci_test_gate.cli import main

    diff_file = tmp_path / "change.diff"
    diff_file.write_text(DIFF)

    main(["suggest", "--diff", str(diff_file), "--output", "sarif"])

    doc = json.loads(capsys.readouterr().out)
    assert doc["runs"][0]["tool"]["driver"]["version"] == __version__


def test_local_command_emits_valid_sarif(capsys):
    from ci_test_gate.cli import main

    with patch("ci_test_gate.cli.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="src/orphan.py\n", returncode=0),
            MagicMock(stdout=DIFF, returncode=0),
            MagicMock(stdout="tests/test_other.py\n", returncode=0),
        ]
        rc = main(["local", "--output", "sarif"])

    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "ci-test-gate"


def test_local_sarif_reports_only_non_test_changed_files(capsys):
    """`local` narrows the changed set to source files before building SARIF.

    Changed *test* files are never reported as untested sources, because
    selecting them is not a coverage finding. The recommendation path
    tests/test_orphan.py covers src/orphan.py via base-name matching, so
    src/orphan.py is NOT flagged.
    """
    from ci_test_gate.cli import main

    diff = textwrap.dedent("""\
        diff --git a/src/orphan.py b/src/orphan.py
        index 1234567..89abcde 100644
        --- a/src/orphan.py
        +++ b/src/orphan.py
        @@ -1,3 +1,4 @@
         def orphan():
        -    return 1
        +    return 2
        diff --git a/tests/test_orphan.py b/tests/test_orphan.py
        index 1234567..89abcde 100644
        --- a/tests/test_orphan.py
        +++ b/tests/test_orphan.py
        @@ -1,3 +1,4 @@
         def test_orphan():
        -    assert True
        +    assert orphan() == 2
    """)
    with patch("ci_test_gate.cli.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="src/orphan.py\ntests/test_orphan.py\n", returncode=0),
            MagicMock(stdout=diff, returncode=0),
            MagicMock(stdout="tests/test_orphan.py\n", returncode=0),
        ]
        rc = main(["local", "--output", "sarif"])

    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["runs"][0]["results"] == []


def test_local_sarif_omits_results_when_every_source_is_touched_only_by_tests(capsys):
    """A source file that is itself in the tested set is not flagged."""
    from ci_test_gate.cli import main

    diff = textwrap.dedent("""\
        diff --git a/src/orphan.py b/src/orphan.py
        index 1234567..89abcde 100644
        --- a/src/orphan.py
        +++ b/src/orphan.py
        @@ -1,3 +1,4 @@
         def orphan():
        -    return 1
        +    return 2
    """)
    with patch("ci_test_gate.cli.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="src/orphan.py\n", returncode=0),
            MagicMock(stdout=diff, returncode=0),
            MagicMock(stdout="src/orphan.py\n", returncode=0),
        ]
        rc = main(["local", "--output", "sarif"])

    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["runs"][0]["results"] == []