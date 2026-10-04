# GitHub Action

`ci-test-gate` ships a composite GitHub Action at
[`action.yml`](https://github.com/yunaremaia/ci-test-gate/blob/main/action.yml)
in the repository root.

## Minimal usage

```yaml
name: ci-test-gate

on:
  pull_request:

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: yunaremaia/ci-test-gate@main
```

With no inputs, the action computes the diff itself:

```bash
BASE="${GITHUB_BASE_REF:-main}"
git diff "origin/${BASE}...HEAD" > /tmp/pr_diff.txt
ci-test-gate suggest --diff /tmp/pr_diff.txt --mode suggest
```

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `diff-file` | no | `''` | Path to a diff file. When empty, the action derives the diff from the PR base ref. |
| `test-files-list` | no | `''` | Path to a file listing all test files, one per line. |
| `mode` | no | `suggest` | `suggest` or `gate`. |
| `github-token` | no | `${{ github.token }}` | GitHub token for PR comments. |

## What the action runs

Four steps, in order:

| Step | What it does |
|---|---|
| `Checkout repository` | `actions/checkout@v5` with `fetch-depth: 0` (full history, so the triple-dot diff resolves) |
| `Set up Python` | `actions/setup-python@v6`, Python 3.11 |
| `Install ci-test-gate` | `pip install ci-test-gate` — the released package, not your checkout |
| `Run ci-test-gate` | `suggest`, either against `diff-file` or a derived diff |

!!! warning "The action installs from PyPI"
    The `Install ci-test-gate` step is `pip install ci-test-gate`, so the action
    runs the released version rather than the code in your branch. To test a
    local change, install from your own checkout in a separate step instead of
    using the action.

## Gate mode

```yaml
      - uses: yunaremaia/ci-test-gate@main
        with:
          diff-file: pr.diff
          mode: gate
```

`--mode gate` exits **2** when a test the classifier marked `required` is not in
the test list, which fails the job.

## Supplying the test list

The action's own `Run ci-test-gate` step does not pass `--test-files`. If you
have not written a diff file, the recommendation is computed with no knowledge
of your suite. For a working gate, generate both inputs in your own steps:

```yaml
name: ci-test-gate

on:
  pull_request:
    branches: [main]

jobs:
  gate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"

      - name: Build the diff
        run: git diff "origin/${{ github.base_ref }}...HEAD" > pr.diff

      - name: Build the test list
        run: git ls-files 'tests/**' 'test/**' '*_test.py' '*.test.ts' '*.test.js' > tests.txt

      - name: Install
        run: pip install ci-test-gate

      - name: Recommend
        run: ci-test-gate suggest --diff pr.diff --test-files tests.txt --output markdown >> "$GITHUB_STEP_SUMMARY"
```

For the full comment-on-the-PR workflow that the repository ships, see
[CI → The test gate workflow](ci.md#the-test-gate-workflow).

## Related

- [Usage](usage.md) — every CLI flag
- [CI](ci.md) — wiring the gate into a workflow, including SARIF
