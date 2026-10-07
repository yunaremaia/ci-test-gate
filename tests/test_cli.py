"""Tests for ci-test-gate CLI."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ci_test_gate.cli import _handle_suggest, main
from ci_test_gate.diff_parser import FileChange


class TestHandleSuggest:
    """Tests for _handle_suggest function."""

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

    def test_gate_mode_returns_zero_when_required_tests_are_covered(self, capsys):
        """Gate mode passes when all required tests are covered.

        This test used to exist twice in this class under the name
        `test_gate_mode_with_required_tests`. The second definition shadowed the
        first at class level, so the earlier body was never collected: an editor
        could change it and never see the test fail. The two bodies were
        identical, so no behaviour was lost by collapsing them into one. F811
        now fails the lint gate if a shadowed test is reintroduced.
        """
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
        args.ran_tests = self._tmp_test_files("tests/test_foo.py\n")
        result = _handle_suggest(args)
        # Gate mode with required tests covered → returns 0
        assert result == 0

    def test_gate_mode_returns_2_when_required_not_in_ran_tests(self, capsys):
        """Gate mode returns 2 when required tests are not in ran_tests."""
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
            mode="gate",
        )
        # ran_tests only has test_bar.py, but required is test_foo.py
        args.ran_tests = self._tmp_test_files("tests/test_bar.py\n")
        result = _handle_suggest(args)
        assert result == 2

    def test_gate_mode_returns_0_when_all_required_in_ran_tests(self, capsys):
        """Gate mode returns 0 when all required tests are in ran_tests."""
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
            mode="gate",
        )
        args.ran_tests = self._tmp_test_files("tests/test_foo.py\ntests/test_bar.py\n")
        result = _handle_suggest(args)
        assert result == 0

    def test_gate_mode_returns_2_when_required_and_no_ran_tests(self, capsys):
        """Gate mode returns 2 when required is non-empty and no ran_tests provided."""
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
        # No ran_tests provided — conservative fail
        result = _handle_suggest(args)
        assert result == 2


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
