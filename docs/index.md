# ci-test-gate

**LLM-powered test selection for CI — run only the tests that matter.**

`ci-test-gate` reads a pull-request diff, decides which of your test files the
change can plausibly affect, and prints a recommendation you can post as a PR
comment or enforce as a merge gate.

## What you can do with it

| I want to… | Use |
|---|---|
| See which tests a PR actually needs | [`suggest`](getting-started.md#run-it-once) |
| Fail the build when a required test was not selected | [`suggest --mode gate`](usage.md#gate-mode) |
| Check a branch before pushing | [`local`](usage.md#the-local-command) |
| Feed a GitHub Actions job that comments on the PR | [`.github/workflows/test-gate.yml`](ci.md#the-test-gate-workflow) |
| Use it as a GitHub Action | [`action.yml`](github-action.md) |
| Run it before every commit | [pre-commit hook](#pre-commit-hook) |
| Consume the result as JSON or SARIF | [Output formats](usage.md#output-formats) |
| Let a model do the classification instead of the heuristic | [LLM mode](configuration.md#llm-mode) |
| Know which test-name conventions are recognised | [Language support](languages.md) |

## Install

```bash
pip install ci-test-gate
```

Python 3.10+. Installed on [PyPI](https://pypi.org/project/ci-test-gate/).

## Run it once

```console
$ ci-test-gate suggest --diff pr.diff --test-files tests.txt
## ci-test-gate Recommendation

**Reasoning:** Heuristic match: 1 required test(s) from 1 changed file(s).

### Required (must run)
- tests/test_app.py

### Optional (can skip)
- tests/test_utils.py

**Estimated CI time savings:** 50%
```

`tests/test_app.py` is required because the diff touched `src/app.py`.
`tests/test_utils.py` is reported optional. Nothing is executed — `ci-test-gate`
only produces the recommendation; your CI job still runs the tests.

## How the recommendation is built

```
┌──────────────────────────────────────────────────┐
│                    GitHub PR                      │
│                     │                             │
│         git diff main...HEAD                     │
│                     │                             │
│                     ▼                             │
│  ┌────────────────────────────────────────────┐  │
│  │           ci-test-gate engine              │  │
│  │                                            │  │
│  │  1. Parse diff into structured changes     │  │
│  │  2. Build context (imports, functions)     │  │
│  │  3. Classify tests (required/recommended/  │  │
│  │     optional)                              │  │
│  │  4. Output recommendation (JSON/Markdown)  │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

Each test file you pass is reduced to a base name — `tests/test_app.py`
becomes `app.py` — and matched against the changed paths. A test whose reduced
name appears in a changed path becomes `required`; every other test becomes
`optional`. Change a `pyproject.toml` instead and the rules widen: see
[Config file changes](usage.md#config-file-changes).

## Two commands, three risk levels

- `suggest` — takes a diff path (or stdin), prints a recommendation
- `local` — auto-discovers the diff and the test files from git, for pre-push use

Both emit `required` / `recommended` / `optional` buckets and an
`estimated_savings_pct` heuristic capped at 95%.

## Pre-commit hook

```yaml
repos:
  - repo: https://github.com/yunaremaia/ci-test-gate
    rev: v0.1.1
    hooks:
      - id: ci-test-gate
```

## Documentation map

- [Getting Started](getting-started.md) — install, first run, gate mode
- [Usage](usage.md) — every flag, verified against `src/ci_test_gate/cli.py`
- [Configuration](configuration.md) — config-file widening, LLM mode, env vars
- [Language Support](languages.md) — per-language test naming conventions
- [GitHub Action](github-action.md) — `action.yml` inputs
- [CI](ci.md) — wiring the gate into a workflow

## Limitations

- It does not measure coverage. It selects tests from the diff; it does not
  prove any selected suite exercises the change.
- It only recommends tests you gave it. A test absent from `--test-files`
  (and not discovered by `local`) can never be recommended.
- Heuristic matching is name-based. Renamed or restructured tests are not
  inferred from an import graph.
- Docs-only and CI-only diffs short-circuit to "no specific tests required".

## License

MIT
