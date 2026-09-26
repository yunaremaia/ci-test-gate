"""Tests for ci-test-gate CLI."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ci_test_gate.cli import _handle_suggest, main
from ci_test_gate.diff_parser import FileChange


class TestHandleSuggest:
    """Tests for _handle_suggest function."""

    def test_config_changes_flag_controls_broad_selection(self, tmp_path, capsys):
        import json

        diff = tmp_path / "change.diff"
        diff.write_text(
            "diff --git a/pyproject.toml b/pyproject.toml\n"
            "--- a/pyproject.toml\n+++ b/pyproject.toml\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        tests = tmp_path / "tests.txt"
        paths = [f"tests/test_module_{i}.py" for i in range(12)]
        tests.write_text("\n".join(paths) + "\n")

        args = ["suggest", "--diff", str(diff), "--test-files", str(tests), "--output", "json"]
        assert main(args) == 0
        broad = json.loads(capsys.readouterr().out)
        assert broad["recommended"] == paths

        assert main(args + ["--config-changes", "normal"]) == 0
        normal = json.loads(capsys.readouterr().out)
        assert normal["recommended"] == []

    def _make_args(self, diff_text, test_files_text=None, output="markdown", mode="suggest"):
        """Helper to create args namespace."""
        args = type("Args", (), {})()
        if diff_text == "-":
            args.diff = Path("-")
        else:
            args.diff = Path("/dev/stdin") if diff_text == "-" else self._tmp_diff(diff_text)
        if test_files_text:
            args.test_files = self._tmp_test_files(test_files_text)
        else:
            args.test_files = None
        args.output = output
        args.mode = mode
        return args

    def _tmp_diff(self, text, tmp_path_factory=None):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".diff")
        with open(fd, "w") as f:
            f.write(text)
        return Path(path)

    def _tmp_test_files(self, text):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".txt")
        with open(fd, "w") as f:
            f.write(text)
        return Path(path)

    def test_basic_suggest_markdown_output(self, capsys):
        args = self._make_args(
            diff_text=textwrap.dedent("""\
                diff --git a/src/foo.py b/src/foo.py
                index 1234567..89abcde 100644
                --- a/src/foo.py
                +++ b/src/foo.py
                @@ -1,3 +1,6 @@
                 def foo():
                -    return 1
                +    return 2
            """),
            test_files_text="tests/test_foo.py\ntests/test_bar.py\n",
            output="markdown",
            mode="suggest",
        )
        result = _handle_suggest(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "ci-test-gate Recommendation" in captured.out
        assert "tests/test_foo.py" in captured.out

    def test_basic_suggest_json_output(self, capsys):
        args = self._make_args(
            diff_text=textwrap.dedent("""\
                diff --git a/src/bar.py b/src/bar.py
                index 1234567..89abcde 100644
                --- a/src/bar.py
                +++ b/src/bar.py
                @@ -1,3 +1,6 @@
                 def bar():
                -    return 1
                +    return 2
            """),
            test_files_text="tests/test_bar.py\ntests/test_baz.py\n",
            output="json",
            mode="suggest",
        )
        result = _handle_suggest(args)
        assert result == 0
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert "required" in data
        assert "tests/test_bar.py" in data["required"]

    def test_gate_mode_no_required_tests(self, capsys):
        """Gate mode returns 0 when no tests are required (nothing to block)."""
        args = self._make_args(
            diff_text=textwrap.dedent("""\
                diff --git a/docs/README.md b/docs/README.md
                index 1234567..89abcde 100644
                --- a/docs/README.md
                +++ b/docs/README.md
                @@ -1,3 +1,6 @@
                 # Project
                +
                +Added docs.
            """),
            test_files_text="test_foo.py\n",
            output="markdown",
            mode="gate",
        )
        result = _handle_suggest(args)
        # Gate mode with no required tests = no block needed → returns 0
        assert result == 0

    def test_gate_mode_with_required_tests(self, capsys):
        args = self._make_args(
            diff_text=textwrap.dedent("""\
                diff --git a/src/foo.py b/src/foo.py
                index 1234567..89abcde 100644
                --- a/src/foo.py
                +++ b/src/foo.py
                @@ -1,3 +1,6 @@
                 def foo():
                -    return 1
                +    return 2
            """),
            test_files_text="tests/test_foo.py\n",
            output="markdown",
            mode="gate",
        )
        result = _handle_suggest(args)
        # Gate mode with required tests returns 0
        assert result == 0

    def test_gate_mode_with_required_tests(self, capsys):
        """Gate mode passes when all required tests are covered."""
        args = self._make_args(
            diff_text=textwrap.dedent("""\
                diff --git a/src/foo.py b/src/foo.py
                index 1234567..89abcde 100644
                --- a/src/foo.py
                +++ b/src/foo.py
                @@ -1,3 +1,6 @@
                 def foo():
                -    return 1
                +    return 2
            """),
            test_files_text="tests/test_foo.py\n",
            output="markdown",
            mode="gate",
        )
        result = _handle_suggest(args)
        # Gate mode with required tests covered → returns 0
        assert result == 0


class TestMain:
    """Tests for main() entry point."""

    def _tmp_diff(self, text):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".diff")
        with open(fd, "w") as f:
            f.write(text)
        return path

    def _tmp_test_files(self, text):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".txt")
        with open(fd, "w") as f:
            f.write(text)
        return path

    def test_suggest_command_markdown(self, capsys):
        diff_path = self._tmp_diff(textwrap.dedent("""\
            diff --git a/src/foo.py b/src/foo.py
            index 1234567..89abcde 100644
            --- a/src/foo.py
            +++ b/src/foo.py
            @@ -1,3 +1,6 @@
             def foo():
            -    return 1
            +    return 2
        """))
        test_path = self._tmp_test_files("tests/test_foo.py\ntests/test_bar.py\n")
        result = main(["suggest", "--diff", diff_path, "--test-files", test_path, "--output", "markdown"])
        assert result == 0
        captured = capsys.readouterr()
        assert "ci-test-gate Recommendation" in captured.out

    def test_suggest_command_json(self, capsys):
        diff_path = self._tmp_diff(textwrap.dedent("""\
            diff --git a/src/bar.py b/src/bar.py
            index 1234567..89abcde 100644
            --- a/src/bar.py
            +++ b/src/bar.py
            @@ -1,3 +1,6 @@
             def bar():
            -    return 1
            +    return 2
        """))
        result = main(["suggest", "--diff", diff_path, "--output", "json"])
        assert result == 0
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert "required" in data
        assert "recommended" in data
        assert "optional" in data

    def test_no_test_files_provided(self, capsys):
        diff_path = self._tmp_diff(textwrap.dedent("""\
            diff --git a/src/foo.py b/src/foo.py
            index 1234567..89abcde 100644
            --- a/src/foo.py
            +++ b/src/foo.py
            @@ -1,3 +1,6 @@
             def foo():
            -    return 1
            +    return 2
        """))
        result = main(["suggest", "--diff", diff_path, "--output", "markdown"])
        assert result == 0
        captured = capsys.readouterr()
        # No test files provided — output still has the recommendation header
        assert "ci-test-gate Recommendation" in captured.out

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
