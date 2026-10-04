# CI

## The test gate workflow

The repository ships
[`.github/workflows/test-gate.yml`](https://github.com/yunaremaia/ci-test-gate/blob/main/.github/workflows/test-gate.yml),
which runs on pull requests and comments the recommendation on the PR.

```yaml
name: CI Test Gate

on:
  pull_request:
    branches: [main, master]

jobs:
  ci-test-gate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          repository: ${{ github.event.pull_request.head.repo.full_name }}
          ref: ${{ github.event.pull_request.head.ref }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Fetch base ref from upstream
        run: git fetch https://github.com/${{ github.event.pull_request.base.repo.full_name }} ${{ github.event.pull_request.base.ref }} --depth=1

      - name: Install ci-test-gate
        run: pip install -e '.[dev]'

      - name: Analyze PR
        run: |
          git diff FETCH_HEAD...HEAD | ci-test-gate suggest --diff - --output markdown > /tmp/gate_output.md
          test -s /tmp/gate_output.md

      - name: Publish recommendation
        uses: actions/github-script@v8
        env:
          GATE_REPORT: /tmp/gate_output.md
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync(process.env.GATE_REPORT, 'utf8');
            fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, report + '\n');
            ...
```

Four details worth copying rather than reinventing:

**It checks out the PR head repository and ref explicitly.** For a fork PR the
merge ref does not contain the fork's commits, so `repository:` and `ref:` are
both set from the event payload.

**It fetches the base ref from upstream separately.** The triple-dot diff needs
`FETCH_HEAD` to point at the real base commit; a shallow `fetch-depth: 0`
checkout of a fork does not have it.

**`test -s /tmp/gate_output.md` fails the job on empty output.** Without it a
silent no-op in the tool would leave a green check and no report.

**The report is read from disk, never interpolated into the script.** Its
content comes from the PR diff, which is untrusted for fork PRs; interpolating
it through a GitHub expression would let a backtick break out of the template
literal and run arbitrary JavaScript in the runner.

### Fork PRs and commenting

Fork pull requests receive a read-only `GITHUB_TOKEN`, so commenting is
impossible by design. The workflow catches the `403` and leaves the report in
the job summary only — that is not a failure. Any other error is genuine and
is propagated.

## Blocking on gate mode

The shipped workflow reports; it does not block. To block, run the CLI with
`--mode gate` in a step whose exit code matters:

```yaml
- name: Enforce required tests
  run: |
    git diff "origin/${{ github.base_ref }}...HEAD" > pr.diff
    git ls-files 'tests/**' > tests.txt
    ci-test-gate suggest --diff pr.diff --test-files tests.txt --mode gate
```

Exit **2** means a required test is not in the list. Exit **1** means the diff
could not be obtained.

## SARIF for code scanning

`--output sarif` emits SARIF 2.1.0 with two rules:

| Rule id | Level |
|---|---|
| `ci-test-gate/missing-required-test` | error |
| `ci-test-gate/untested-changed-file` | warning |

```yaml
- name: Recommend
  run: ci-test-gate suggest --diff pr.diff --test-files tests.txt --output sarif > gate.sarif

- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: gate.sarif
```

## Running only the recommended tests

The tool selects; it does not run. To act on the recommendation, read the JSON
output and pass the `required` list to your runner:

```yaml
- name: Recommend
  id: gate
  run: |
    git diff "origin/${{ github.base_ref }}...HEAD" > pr.diff
    git ls-files 'tests/**' > tests.txt
    ci-test-gate suggest --diff pr.diff --test-files tests.txt --output json > gate.json

- name: Run required tests
  run: pytest $(jq -r '.required[]' gate.json)
```

If the list is empty, that `pytest` call runs nothing — guard it with
`jq -e '.required | length > 0'` if an empty selection should fall back to the
full suite.

## Local parity

Everything above is reproducible before pushing:

```console
$ ci-test-gate local --base origin/main
```

`local` runs the same classifier over the same diff, discovering the test list
from git. It exits 1 if the base ref cannot be diffed.
