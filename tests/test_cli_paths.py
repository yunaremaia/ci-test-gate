"""Tests for the remaining CLI paths in ci_test_gate.cli.

Covers the `local`/`suggest` failure branches, gate mode returning exit code
2, stdin input, and the `__main__` entry point.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ci_test_gate.cli import main


DIFF = textwrap.dedent("""\
    diff --git a/src/foo.py b/src/foo.py
    index 1234567..89abcde 100644
    --- a/src/foo.py
    +++ b/src/foo.py
    @@ -1,3 +1,6 @@
     def foo():
    -    return 1
    +    return 2
""")


def _local(*args: str, diff: str = DIFF, test_files: str = "tests/test_foo.py\n", llm_required=None, ran_tests=None):
    """Drive the `local` command with a scripted sequence of git calls.

    When `llm_required` is given, the LLM classifier is stubbed to report
    exactly that list as its required tests.
    """
    llm_patch = None
    if llm_required is not None:
        instance = MagicMock()
        instance.classify.return_value = MagicMock(
            required=list(llm_required),
            recommended=[],
            to_json=lambda: '{"required": []}',
            to_markdown=lambda: "llm markdown",
        )
        llm_patch = patch("ci_test_gate.cli.LLMTestClassifier", return_value=instance)

    with patch("ci_test_gate.cli.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="src/foo.py\n", returncode=0),
            MagicMock(stdout=diff, returncode=0),
            MagicMock(stdout=test_files, returncode=0),
        ]
        if ran_tests is not None:
            args = (*args, "--ran-tests", ran_tests)
        if llm_patch is not None:
            with llm_patch:
                return main(["local", *args])
        return main(["local", *args])


# ---------------------------------------------------------------------------
# `local` failure branches
# ---------------------------------------------------------------------------


def test_local_reports_a_failure_when_the_diff_body_cannot_be_read(capsys):
    """The second git call (the diff body) can fail after --name-only succeeded."""
    import subprocess as real_subprocess

    ok = MagicMock(stdout="src/foo.py\n", returncode=0)
    with patch("ci_test_gate.cli.subprocess.run") as mock_run:
        mock_run.side_effect = [
            ok,
            real_subprocess.CalledProcessError(1, "git", stderr="fatal: bad object"),
        ]
        rc = main(["local"])

    assert rc == 1
    assert "ERROR: Failed to get diff:" in capsys.readouterr().err


def test_local_tolerates_a_failing_test_file_discovery(capsys):
    """`git ls-files` failing must not abort the command."""
    import subprocess as real_subprocess

    with patch("ci_test_gate.cli.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="src/foo.py\n", returncode=0),
            MagicMock(stdout=DIFF, returncode=0),
            real_subprocess.CalledProcessError(1, "git", stderr="fatal: not a git repository"),
        ]
        rc = main(["local", "--output", "json"])

    assert rc == 0
    assert "required" in capsys.readouterr().out


def test_local_gate_mode_returns_two_when_a_required_test_is_not_in_the_list():
    """Exit code 2 needs a classifier that names a test outside the list.

    The heuristic only ever marks tests that came *from* `git ls-files`, so it
    cannot produce a missing required test; the gate is reachable through a
    classifier that reports one the provided list does not contain.
    """
    rc = _local(
        "--mode",
        "gate",
        "--llm",
        test_files="tests/test_somethingelse.py\n",
        llm_required=["tests/test_foo.py"],
    )

    assert rc == 2


def test_local_gate_mode_returns_zero_when_required_tests_are_covered(tmp_path):
    ran_tests = tmp_path / "ran.txt"
    ran_tests.write_text("tests/test_foo.py\n")
    rc = _local("--mode", "gate", test_files="tests/test_foo.py\n", ran_tests=str(ran_tests))

    assert rc == 0


def test_local_suggest_mode_never_blocks(capsys):
    rc = _local("--mode", "suggest", test_files="tests/test_somethingelse.py\n")

    assert rc == 0
    assert "required" in capsys.readouterr().out


def test_local_markdown_output_is_the_default(capsys):
    rc = _local()

    assert rc == 0
    assert "ci-test-gate Recommendation" in capsys.readouterr().out


def test_local_uses_the_llm_classifier_when_asked():
    with patch("ci_test_gate.cli.LLMTestClassifier") as mock_llm:
        instance = MagicMock()
        instance.classify.return_value = MagicMock(
            to_json=lambda: '{"required": []}',
            to_markdown=lambda: "llm markdown",
            required=[],
            recommended=[],
        )
        mock_llm.return_value = instance
        with patch("ci_test_gate.cli.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="src/foo.py\n", returncode=0),
                MagicMock(stdout=DIFF, returncode=0),
                MagicMock(stdout="tests/test_foo.py\n", returncode=0),
            ]
            rc = main(["local", "--llm", "--llm-api-key", "sk-test", "--llm-model", "gpt-4o"])

    assert rc == 0
    assert mock_llm.call_args[0][0] == {
        "classifier_type": "llm",
        "api_key": "sk-test",
        "model": "gpt-4o",
        "config_changes": "broad",
    }


def test_local_passes_config_changes_normal_through():
    with patch("ci_test_gate.cli.TestClassifier") as mock_cls:
        with patch("ci_test_gate.cli.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="src/foo.py\n", returncode=0),
                MagicMock(stdout=DIFF, returncode=0),
                MagicMock(stdout="tests/test_foo.py\n", returncode=0),
            ]
            main(["local", "--config-changes", "normal"])

    assert mock_cls.call_args.kwargs["config"] == {"config_changes": "normal"}


# ---------------------------------------------------------------------------
# `suggest` paths
# ---------------------------------------------------------------------------


def test_suggest_reads_the_diff_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(DIFF))

    rc = main(["suggest", "--diff", "-"])

    assert rc == 0
    assert "ci-test-gate Recommendation" in capsys.readouterr().out


def test_suggest_gate_mode_returns_two_when_a_required_test_is_missing(tmp_path):
    """Gate exit 2 via a classifier naming a test the list does not contain."""
    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)
    test_list = tmp_path / "tests.txt"
    test_list.write_text("tests/test_unrelated.py\n")

    instance = MagicMock()
    instance.classify.return_value = MagicMock(
        required=["tests/test_foo.py"],
        recommended=[],
        to_json=lambda: '{"required": []}',
        to_markdown=lambda: "llm markdown",
    )
    with patch("ci_test_gate.cli.LLMTestClassifier", return_value=instance):
        rc = main([
            "suggest",
            "--diff", str(diff_file),
            "--test-files", str(test_list),
            "--mode", "gate",
            "--llm",
            "--llm-api-key", "sk-test",
        ])

    assert rc == 2


def test_suggest_gate_mode_returns_zero_when_required_tests_are_covered(tmp_path):
    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)
    test_list = tmp_path / "tests.txt"
    test_list.write_text("tests/test_foo.py\n")
    ran_tests = tmp_path / "ran.txt"
    ran_tests.write_text("tests/test_foo.py\n")

    rc = main(["suggest", "--diff", str(diff_file), "--test-files", str(test_list), "--mode", "gate", "--ran-tests", str(ran_tests)])

    assert rc == 0


def test_suggest_uses_the_llm_classifier_when_asked(tmp_path):
    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)

    with patch("ci_test_gate.cli.LLMTestClassifier") as mock_llm:
        instance = MagicMock()
        instance.classify.return_value = MagicMock(
            to_json=lambda: '{"required": []}',
            to_markdown=lambda: "llm markdown",
            required=[],
            recommended=[],
        )
        mock_llm.return_value = instance
        rc = main(["suggest", "--diff", str(diff_file), "--llm", "--llm-api-key", "sk-test"])

    assert rc == 0
    assert mock_llm.call_args[0][0]["classifier_type"] == "llm"
    assert mock_llm.call_args[0][0]["api_key"] == "sk-test"


def test_suggest_passes_config_changes_normal_through(tmp_path):
    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)

    with patch("ci_test_gate.cli.TestClassifier") as mock_cls:
        main(["suggest", "--diff", str(diff_file), "--config-changes", "normal"])

    assert mock_cls.call_args.kwargs["config"] == {"config_changes": "normal"}


def test_suggest_without_a_test_file_list_still_succeeds(tmp_path, capsys):
    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)

    rc = main(["suggest", "--diff", str(diff_file)])

    assert rc == 0
    assert "ci-test-gate Recommendation" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Argument-level behaviour
# ---------------------------------------------------------------------------


def test_version_flag_exits_zero(capsys):
    from ci_test_gate import __version__

    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_a_missing_subcommand_is_an_argparse_error():
    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2


def test_an_unknown_subcommand_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["nonsense"])

    assert exc.value.code == 2


def test_help_is_available():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0


def test_module_entry_point_runs_as_a_script(tmp_path):
    """`python -m ci_test_gate.cli` must reach main() and exit 0."""
    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)

    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "ci_test_gate.cli", "suggest", "--diff", str(diff_file)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(repo_root / "src"), "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert "ci-test-gate Recommendation" in result.stdout


def test_main_entry_point_executes_the_module_body(tmp_path, monkeypatch):
    """Run cli.py as ``__main__`` so the `sys.exit(main())` guard is exercised.

    `runpy.run_module` executes the module with ``__name__ == "__main__"``,
    which covers the guard at the bottom of `cli.py` in-process. argv is
    pointed at a real diff so `main()` completes and exits 0.
    """
    import runpy

    diff_file = tmp_path / "c.diff"
    diff_file.write_text(DIFF)
    monkeypatch.setattr(sys, "argv", ["ci-test-gate", "suggest", "--diff", str(diff_file)])
    # Drop the cached module so runpy re-executes the file rather than warning
    # that it was already in sys.modules.
    monkeypatch.delitem(sys.modules, "ci_test_gate.cli", raising=False)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("ci_test_gate.cli", run_name="__main__")

    assert exc.value.code == 0