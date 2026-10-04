# Usage

Everything below is taken from `src/ci_test_gate/cli.py`. Two subcommands:
`suggest` and `local`.

```console
$ ci-test-gate --help
usage: ci-test-gate [-h] [--version] {suggest,local} ...

LLM-powered test selection for CI — run only the tests that matter

positional arguments:
  {suggest,local}
    suggest        Suggest which tests to run
    local          Local pre-push validation (auto-discovers diff)

options:
  -h, --help       show this help message and exit
  --version        show program's version number and exit
```

## The `suggest` command

```console
$ ci-test-gate suggest --help
usage: ci-test-gate suggest [-h] --diff DIFF [--test-files TEST_FILES]
                            [--mode {suggest,gate}]
                            [--output {json,markdown,sarif}]
                            [--config-changes {broad,normal}] [--llm]
                            [--llm-api-key LLM_API_KEY]
                            [--llm-model LLM_MODEL]
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--diff DIFF` | yes | — | Path to diff file, or `-` for stdin |
| `--test-files TEST_FILES` | no | none | File listing all test files, one per line |
| `--mode {suggest,gate}` | no | `suggest` | `suggest` prints; `gate` exits 2 if a required test is not in the list |
| `--output {json,markdown,sarif}` | no | `markdown` | Output format |
| `--config-changes {broad,normal}` | no | `broad` | How to classify when a project/dependency config file changes |
| `--llm` | no | off | Use LLM semantic classification instead of heuristics |
| `--llm-api-key` | no | `$OPENAI_API_KEY` | OpenAI-compatible API key |
| `--llm-model` | no | `$CI_TEST_GATE_MODEL`, else `gpt-4o-mini` | Model name |

Without `--test-files` the tool knows nothing about your test suite, so it
recommends nothing. Pass the list, or use `local`.

## The `local` command

```console
$ ci-test-gate local --help
usage: ci-test-gate local [-h] [--base BASE] [--mode {suggest,gate}]
                          [--output {json,markdown,sarif}]
                          [--config-changes {broad,normal}] [--llm]
                          [--llm-api-key LLM_API_KEY] [--llm-model LLM_MODEL]
```

`local` has no `--diff` and no `--test-files`: it discovers both from git.
Its flags are identical to `suggest` except for the addition of `--base`.

| Flag | Default | Description |
|---|---|---|
| `--base BASE` | `main` | Base branch to diff against |
| `--mode {suggest,gate}` | `suggest` | Same as `suggest` |
| `--output {json,markdown,sarif}` | `markdown` | Same as `suggest` |
| `--config-changes {broad,normal}` | `broad` | Same as `suggest` |
| `--llm` | off | Same as `suggest` |
| `--llm-api-key` | `$OPENAI_API_KEY` | Same as `suggest` |
| `--llm-model` | `$CI_TEST_GATE_MODEL`, else `gpt-4o-mini` | Same as `suggest` |

!!! note "`local` discovers tests with git, not with a heuristic"
    It runs `git ls-files` over `tests/**`, `test/**`, `*_test.py`,
    `*.test.ts` and `*.test.js`. A test file outside those patterns is invisible
    to `local`, even if `suggest` would recommend it if you listed it.

## Gate mode

`--mode gate` prints the same recommendation, then compares the `required`
bucket against your test-file list. If any required test is missing, the exit
code is **2**:

```console
$ ci-test-gate suggest --diff pr.diff --test-files tests.txt --mode gate
$ echo $?
0
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Recommendation produced, and in `gate` mode nothing required was missing |
| 1 | `local` could not run `git diff` against the base branch |
| 2 | `gate` mode only: a required test is not in the supplied list |

## Output formats

### `markdown` (default)

```markdown
## ci-test-gate Recommendation

**Reasoning:** Heuristic match: 1 required test(s) from 1 changed file(s).

### Required (must run)
- tests/test_app.py

### Optional (can skip)
- tests/test_utils.py

**Estimated CI time savings:** 50%
```

### `json`

```json
{
  "required": [
    "tests/test_app.py"
  ],
  "recommended": [],
  "optional": [
    "tests/test_utils.py"
  ],
  "reasoning": "Heuristic match: 1 required test(s) from 1 changed file(s).",
  "estimated_savings_pct": 50
}
```

`recommended` is populated by the config-change widening, not by ordinary path
matching.

### `sarif`

SARIF 2.1.0 for GitHub Code Scanning. Two rule ids are emitted:

| Rule id | Level | Meaning |
|---|---|---|
| `ci-test-gate/missing-required-test` | error | A source file changed but its required test suite was not selected |
| `ci-test-gate/untested-changed-file` | warning | A changed source file has no test suite selected at all |

```bash
ci-test-gate suggest --diff pr.diff --test-files tests.txt --output sarif > gate.sarif
```

## Config file changes

A change to a project or dependency configuration file can break any test in
the repository, not only tests whose name resembles the changed file.
Name-based matching under-selects in that case, and for a test gate that is the
more dangerous failure.

With the default `--config-changes broad`, when any recognised config file
appears in the diff, **every** test you supplied is recommended. Tests directly
matched to a changed source file stay `required`; the rest become `recommended`.

```console
$ ci-test-gate suggest --diff pyproject.diff --test-files tests.txt
## ci-test-gate Recommendation

**Reasoning:** Project config changed (pyproject.toml); recommending all 2 remaining test(s).

### Recommended
- tests/test_app.py
- tests/test_utils.py

**Estimated CI time savings:** 95%
```

Pass `--config-changes normal` to restore ordinary path matching:

```console
$ ci-test-gate suggest --diff pyproject.diff --test-files tests.txt --config-changes normal
## ci-test-gate Recommendation

**Reasoning:** Heuristic match: 0 required test(s) from 1 changed file(s).

### Optional (can skip)
- tests/test_app.py
- tests/test_utils.py

**Estimated CI time savings:** 50%
```

The flag is available on `suggest` and `local`, and applies in `--llm` mode too.

### Which files count as config files

From `PROJECT_CONFIG_FILES` in `src/ci_test_gate/context_builder.py`, matched on
**basename**, so `services/api/package.json` counts:

- Python: `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`,
  `tox.ini`, `pytest.ini`, `pipfile`, `poetry.lock`, `pdm.lock`
- JavaScript/TypeScript: `package.json`, `package-lock.json`, `yarn.lock`,
  `pnpm-lock.yaml`, `tsconfig.json`, `composer.json`, `composer.lock`
- Go/Rust/other: `go.mod`, `go.sum`, `cargo.toml`, `cargo.lock`, `gemfile`,
  `gemfile.lock`, `pom.xml`, `build.gradle`

!!! warning "The widening depends on your test-file list"
    It cannot recommend a test that was never passed via `--test-files` and was
    not discovered by `local`. It never omits a known test for a config change,
    but it does not measure coverage and cannot prove that any selected suite
    exercises the changed dependency.

## Doc-only and CI-only diffs

If nothing matched, and every changed path is a workflow/YAML file, or every
changed path is documentation, the classifier short-circuits:

```
**Reasoning:** CI-only changes detected; no specific tests required.
**Estimated CI time savings:** 80%
```

```
**Reasoning:** Doc-only changes detected; no specific tests required.
```

## Binary diffs

A diff containing only binary files produces no source classification; every
supplied test is reported optional:

```
**Reasoning:** Binary-only changes; no source files to classify.
```

## Pre-commit hook

The repository ships `.pre-commit-hooks.yaml`:

```yaml
- id: ci-test-gate
  name: Suggest tests to run based on diff
  entry: ci-test-gate suggest
  language: python
  files: '\.(py|js|ts|go|rs|java|rb)$'
  additional_dependencies:
    - "ci-test-gate>=0.1.0"
  args: ["--mode", "suggest"]
```

Note that the hook runs `suggest` with no `--diff` or `--test-files`; add them
through your own `args` if you want a working recommendation from the hook.

```yaml
repos:
  - repo: https://github.com/yunaremaia/ci-test-gate
    rev: v0.1.1
    hooks:
      - id: ci-test-gate
        args: ["--diff", "-", "--test-files", "tests.txt"]
```
