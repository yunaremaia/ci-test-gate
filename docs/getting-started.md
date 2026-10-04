# Getting Started

## Install

```bash
pip install ci-test-gate
```

Requires Python 3.10 or newer. The package is published on
[PyPI](https://pypi.org/project/ci-test-gate/) as `ci-test-gate`, and the
console script is `ci-test-gate`.

To track the tip of `main` instead of the latest release:

```bash
pip install git+https://github.com/yunaremaia/ci-test-gate.git
```

Check the install:

```console
$ ci-test-gate --version
ci-test-gate 0.1.1
```

## Prepare the two inputs

`suggest` needs a diff and a list of test files.

**1. The diff.** Either write `git diff` to a file:

```bash
git diff origin/main...HEAD > pr.diff
```

…or pipe it in and pass `--diff -`:

```bash
git diff origin/main...HEAD | ci-test-gate suggest --diff -
```

The diff must be real unified diff text. For a pull request on GitHub, the
`git diff` form above is the usual source.

**2. The test file list.** One path per line, relative to the repository root:

```bash
git ls-files 'tests/**' > tests.txt
```

```console
$ cat tests.txt
tests/test_app.py
tests/test_utils.py
```

This list is the ceiling on what `ci-test-gate` can recommend. A test that is
not in it can never appear in the output — see
[Limitations](index.md#limitations).

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

Given a diff touching `src/app.py`, `tests/test_app.py` matches by reduced name
and is required; `tests/test_utils.py` does not match and is optional. The tool
reports — it does not run anything.

## Read the three buckets

| Bucket | Meaning |
|---|---|
| `required` | A changed path matches this test's reduced name. Run it. |
| `recommended` | Used for the config-change widening — see below. |
| `optional` | Known test, but nothing in the diff points at it. Safe to skip. |

`estimated_savings_pct` is a name-count heuristic (`1 - required/total`),
capped at 95%. It is not measured CI time.

## Turn it into a gate

`--mode gate` exits **2** when a test the classifier marked `required` is not
in the list of tests you are about to run. A clean run exits 0.

```console
$ ci-test-gate suggest --diff pr.diff --test-files tests.txt --mode gate
$ echo $?
0
```

## Skip git entirely with `local`

Inside a repository, `local` discovers the diff and the tests for you:

```console
$ ci-test-gate local --base main
```

It runs `git diff --name-only <base>...HEAD`, then `git diff <base>...HEAD`
for the content, then `git ls-files` over `tests/**`, `test/**`, `*_test.py`,
`*.test.ts`, `*.test.js` for the test list. No changes means it prints
`No changes detected.` and exits 0.

## Next

- Every flag, verified against `src/ci_test_gate/cli.py` — [Usage](usage.md)
- Config-change widening and LLM mode — [Configuration](configuration.md)
- Commenting on the PR from Actions — [CI](ci.md)
