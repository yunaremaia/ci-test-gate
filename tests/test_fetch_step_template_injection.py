"""Executable regression test for the fetch step's template-injection surface.

tests/test_workflow_gate.py asserts that the workflow *looks* right. This module
does the stronger thing: it extracts the ``run:`` block of the fetch step, replays
it the way the runner does, and executes it with hostile ``${{ }}`` values.

The rule this test exists to pin down is that the runner substitutes a ``${{ }}``
expression into the script text *before* bash parses the line. Quoting the
expression in the YAML therefore protects nothing -- the hostile text is already
part of the source when the shell sees it. The only shape that holds is to route
the value through the step ``env:`` and read it as a shell variable, which leaves
the command line fixed regardless of what the value contains.

Both assertions below run the real command, so they are red against the pre-fix
workflow and green after it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test-gate.yml"
STEP_NAME = "Fetch base ref from upstream"

EXPRESSION = re.compile(r"\$\{\{(?P<body>.*?)\}\}", re.DOTALL)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    if not WORKFLOW.is_file():
        pytest.skip(f"workflow not present at {WORKFLOW}")
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fetch_step_source(workflow_text: str) -> str:
    """The raw YAML text of the fetch step, comments and all.

    Raw text rather than the parsed dict: whether an expression is interpolated
    into the script or read from the environment is invisible after YAML parsing,
    and that distinction is the whole point of the test.
    """
    lines = workflow_text.split("\n")
    start = next(
        (i for i, line in enumerate(lines) if re.match(rf"^\s*-\s+name:\s*{STEP_NAME}\s*$", line)),
        None,
    )
    assert start is not None, f"no step named {STEP_NAME!r} in the workflow"
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        if line.lstrip().startswith("-") and len(line) - len(line.lstrip()) <= indent:
            end = index
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def fetch_step(workflow_text: str) -> dict:
    workflow = yaml.safe_load(workflow_text)
    steps = workflow["jobs"]["ci-test-gate"]["steps"]
    return next(step for step in steps if step.get("name") == STEP_NAME)


def _expressions(run_command: str, step: dict) -> list[str]:
    """Every distinct ``${{ }}`` expression the step feeds to bash, in order.

    Scoped to the ``run:`` command and the ``env:`` block on purpose. Whole-step
    text would also match expressions inside YAML comments, which never reach the
    shell, so a prose mention of ``${{ }}`` would register as a live payload.
    """
    sources = [run_command, *[str(v) for v in (step.get("env") or {}).values()]]
    seen: dict[str, None] = {}
    for text in sources:
        for match in EXPRESSION.finditer(text):
            seen.setdefault(match.group("body").strip(), None)
    return list(seen)


def _hostile(expression: str, marker_dir: Path) -> str:
    """A value for ``expression`` that plants a marker if it is ever executed.

    Both values carry ``;`` so that an inline interpolation splits the line and
    runs a second command, and ``$( )`` so that a value reaching bash unquoted
    survives a naive attempt to quote only part of the line.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", expression)[-40:]
    if expression.endswith("base.ref"):
        return f"main$(touch {marker_dir}/PWNED_{slug}); #"
    return f"acme/gate; touch {marker_dir}/PWNED_{slug}; #"


def _render(step_source: str, payloads: dict[str, str]) -> str:
    """The script text the runner hands to bash, expressions substituted.

    This is what the runner does before the shell parses anything. A step that
    routes the value through ``env:`` is unaffected -- the substitution happens in
    the environment instead -- so both shapes converge on one rendered command and
    a single execution can compare them.
    """
    return EXPRESSION.sub(lambda m: payloads[m.group("body").strip()], step_source)


def _run_command(step_source: str) -> str:
    """The step's shell command, in either ``run: <inline>`` or ``run: |`` form.

    Both shapes are handled because a harness that quietly executes the wrong text
    would go green for the wrong reason, which is worse than no harness at all.
    """
    lines = step_source.split("\n")
    for index, line in enumerate(lines):
        match = re.match(r"^\s*run:[ \t]*(?P<value>.*)$", line)
        if not match:
            continue
        if match.group("value").strip() not in {"|", ">", "|-", ">-", "|+", ">+"}:
            return match.group("value")
        indent = len(line) - len(line.lstrip())
        block = []
        for body in lines[index + 1 :]:
            if body.strip() and len(body) - len(body.lstrip()) <= indent:
                break
            block.append(body)
        if not any(body.strip() for body in block):
            raise AssertionError(f"{STEP_NAME} has an empty run: block")
        return "\n".join(body[indent:] for body in block)
    raise AssertionError(f"{STEP_NAME} has no run: command")


def _env_for(step: dict, payloads: dict[str, str]) -> dict[str, str]:
    """The step's ``env:`` block, every value replaced by its hostile counterpart."""
    env = {}
    for name, value in (step.get("env") or {}).items():
        rendered = _render(str(value), payloads)
        env[name] = rendered
    return env


def _fake_git(bin_dir: Path, argv_log: Path) -> None:
    """A ``git`` stand-in that records argv and never touches the network."""
    bin_dir.mkdir(exist_ok=True)
    git = bin_dir / "git"
    git.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> {argv_log}\nexit 0\n', encoding="utf-8"
    )
    git.chmod(0o755)


def _run_fetch_step(step_source: str, step: dict, marker_dir: Path, tmp_path: Path) -> list[str]:
    """Execute the rendered fetch step; return the argv its ``git`` received."""
    if shutil.which("bash") is None:
        pytest.skip("bash is not available")

    argv_log = tmp_path / "argv.log"
    _fake_git(tmp_path / "bin", argv_log)

    command = _run_command(step_source)
    payloads = {body: _hostile(body, marker_dir) for body in _expressions(command, step)}
    script = tmp_path / "step.sh"
    script.write_text(_render(command, payloads), encoding="utf-8")

    env = {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        **_env_for(step, payloads),
    }
    subprocess.run(
        ["bash", "-e", str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return argv_log.read_text(encoding="utf-8").splitlines() if argv_log.exists() else []


@pytest.fixture
def execution(
    fetch_step_source: str, fetch_step: dict, tmp_path: Path
) -> tuple[list[str], dict[str, str]]:
    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    payloads = {
        body: _hostile(body, marker_dir)
        for body in _expressions(_run_command(fetch_step_source), fetch_step)
    }
    argv = _run_fetch_step(fetch_step_source, fetch_step, marker_dir, tmp_path)
    return argv, payloads


def test_no_embedded_command_runs(
    execution: tuple[list[str], dict[str, str]], tmp_path: Path
) -> None:
    """Not one command from the payload may run, in either interpolation shape."""
    argv, _ = execution
    assert argv, "the fetch command never reached git; the test is exercising nothing"

    marker_dir = tmp_path / "markers"
    planted = sorted(p.name for p in marker_dir.iterdir())
    assert not planted, (
        f"the fetch step executed commands embedded in a ${{{{ }}}} value: {planted}. "
        "The runner substitutes the expression before bash parses the line, so the "
        "value must travel through the step env, not through the script text."
    )


def test_payload_arrives_as_a_single_argument(execution: tuple[list[str], dict[str, str]]) -> None:
    """The malicious value must reach ``git`` intact: one argument, unexecuted."""
    argv, payloads = execution

    assert argv[0] == "fetch", f"git did not receive a fetch subcommand: {argv}"
    assert "--depth=1" in argv, (
        f"the fetch lost --depth=1: {argv}. A payload that swallowed the rest of the "
        "command line has broken the fetch, whatever else it managed to do."
    )
    for body, hostile in payloads.items():
        holders = [arg for arg in argv if hostile in arg]
        assert len(holders) == 1, (
            f"the value for {body!r} reached git as {len(holders)} argument(s) {holders}; "
            f"git saw {argv}. Splitting it apart is what let the payload run."
        )


def test_script_body_carries_no_expression(fetch_step_source: str) -> None:
    """The shell line itself must be free of untrusted interpolation."""
    assert not EXPRESSION.search(_run_command(fetch_step_source)), (
        "the fetch command interpolates a ${{ }} expression straight into the shell "
        "line; pass it through env and read it as a shell variable instead"
    )
