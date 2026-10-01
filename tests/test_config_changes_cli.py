"""CLI-level tests for ``--config-changes`` (#71)."""

from __future__ import annotations

import json
import textwrap

import pytest

from ci_test_gate.cli import main

MANY_TESTS = [f"tests/test_mod{i:02d}.py" for i in range(12)]

CONFIG_DIFF = textwrap.dedent("""\
    diff --git a/pyproject.toml b/pyproject.toml
    --- a/pyproject.toml
    +++ b/pyproject.toml
    @@ -1 +1,2 @@
     [project]
    +dependencies = ["httpx>=1.0"]
    """)

MIXED_DIFF = textwrap.dedent("""\
    diff --git a/pyproject.toml b/pyproject.toml
    --- a/pyproject.toml
    +++ b/pyproject.toml
    @@ -1 +1,2 @@
     [project]
    +dependencies = ["httpx>=1.0"]
    diff --git a/src/mod01.py b/src/mod01.py
    --- a/src/mod01.py
    +++ b/src/mod01.py
    @@ -1 +1,2 @@
     def helper():
    +    return 1
    """)

README_DIFF = textwrap.dedent("""\
    diff --git a/README.md b/README.md
    --- a/README.md
    +++ b/README.md
    @@ -1 +1,2 @@
     # Title
    +A new sentence.
    """)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "config.diff").write_text(CONFIG_DIFF)
    (tmp_path / "mixed.diff").write_text(MIXED_DIFF)
    (tmp_path / "readme.diff").write_text(README_DIFF)
    (tmp_path / "tests.txt").write_text("\n".join(MANY_TESTS) + "\n")
    return tmp_path


def _suggest_json(workspace, diff_name="config.diff", extra=()) -> dict:
    """Run the CLI and capture the JSON it prints on stdout."""
    import io
    import contextlib

    buf = io.StringIO()
    argv = [
        "suggest",
        "--diff", str(workspace / diff_name),
        "--test-files", str(workspace / "tests.txt"),
        "--output", "json",
        *extra,
    ]
    with contextlib.redirect_stdout(buf):
        exit_code = main(argv)
    assert exit_code == 0, f"CLI exited {exit_code}"
    return json.loads(buf.getvalue())


class TestConfigChangesFlag:
    def test_default_recommends_every_test(self, workspace):
        data = _suggest_json(workspace)
        assert data["recommended"] == MANY_TESTS
        assert data["optional"] == []

    def test_normal_mode_keeps_ordinary_matching(self, workspace):
        data = _suggest_json(workspace, extra=["--config-changes", "normal"])
        assert data["recommended"] == []
        assert data["optional"] == MANY_TESTS

    def test_mixed_change_keeps_required_and_recommends_rest(self, workspace):
        data = _suggest_json(workspace, diff_name="mixed.diff")
        assert data["required"] == ["tests/test_mod01.py"]
        assert set(data["recommended"]) == set(MANY_TESTS) - {"tests/test_mod01.py"}

    def test_mixed_change_normal_mode(self, workspace):
        data = _suggest_json(
            workspace, diff_name="mixed.diff", extra=["--config-changes", "normal"]
        )
        assert data["required"] == ["tests/test_mod01.py"]
        assert data["recommended"] == []

    def test_readme_change_is_not_a_config_change(self, workspace):
        data = _suggest_json(workspace, diff_name="readme.diff")
        assert data["recommended"] == []
        assert data["optional"] == MANY_TESTS

    def test_flag_rejects_unknown_value(self, workspace):
        with pytest.raises(SystemExit):
            main([
                "suggest",
                "--diff", str(workspace / "config.diff"),
                "--test-files", str(workspace / "tests.txt"),
                "--config-changes", "sideways",
            ])


class TestFlagPresentOnBothSubcommands:
    def test_suggest_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["suggest", "--help"])
        assert "--config-changes" in capsys.readouterr().out

    def test_local_help(self, capsys):
        with pytest.raises(SystemExit):
            main(["local", "--help"])
        assert "--config-changes" in capsys.readouterr().out