"""Tests for context builder."""

import pytest

from ci_test_gate.context_builder import ContextBuilder, ChangeContext
from ci_test_gate.diff_parser import FileChange


class TestContextBuilder:
    def test_build_empty(self):
        builder = ContextBuilder()
        context = builder.build([])
        assert isinstance(context, ChangeContext)
        assert len(context.changed_files) == 0

    def test_build_with_changes(self):
        changes = [
            FileChange(path="src/main.py", added_lines=["import os"]),
            FileChange(path="tests/test_main.py", added_lines=["def test_foo():"]),
        ]
        builder = ContextBuilder()
        context = builder.build(changes)
        assert len(context.test_files_present) == 1
        assert context.test_files_present[0] == "tests/test_main.py"

    def test_detect_pytest_runner(self):
        changes = [
            FileChange(path="pyproject.toml", added_lines=["pytest = '^8.0'"]),
        ]
        builder = ContextBuilder()
        context = builder.build(changes)
        assert "pytest" in context.test_runners_detected

    def test_estimate_scope_small(self):
        changes = [
            FileChange(path="a.py", added_lines=["+line"]),
        ]
        builder = ContextBuilder()
        context = builder.build(changes)
        assert context.estimated_scope == "small"

    def test_estimate_scope_large(self):
        changes = [FileChange(path=f"file{i}.py", added_lines=[f"+line{j}" for j in range(20)]) for i in range(30)]
        builder = ContextBuilder()
        context = builder.build(changes)
        assert context.estimated_scope == "large"

    def test_extract_imports_python(self):
        changes = [
            FileChange(path="src/main.py", added_lines=["from os import path", "import sys"]),
        ]
        builder = ContextBuilder()
        context = builder.build(changes)
        assert "src/main.py" in context.imports_added
        assert "os" in context.imports_added["src/main.py"]

    def test_prompt_context_output(self):
        changes = [
            FileChange(path="src/main.py"),
        ]
        builder = ContextBuilder()
        context = builder.build(changes)
        prompt = context.to_prompt_context()
        assert "Scope:" in prompt
        assert "Changed files:" in prompt


class TestChangeContext:
    def test_to_json(self):
        ctx = ChangeContext(changed_files=[])
        output = ctx.to_prompt_context()
        assert "Scope: small" in output

@pytest.mark.parametrize("extension", ["ts", "js"])
@pytest.mark.parametrize("prefix", ["", "export ", "async ", "export async "])
def test_javascript_function_names(extension, prefix):
    path = f"src/client.{extension}"
    change = FileChange(
        path=path,
        added_lines=[f"  {prefix}function fetchData() {{"],
        removed_lines=[f"  {prefix}function oldFetch() {{"],
    )
    context = ContextBuilder().build([change])
    assert context.functions_changed == {path: ["+fetchData", "-oldFetch"]}
    assert f"{path}: +fetchData, -oldFetch" in context.to_prompt_context()
