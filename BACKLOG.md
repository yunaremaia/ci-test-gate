# Backlog

## ci-test-gate: PR #88 gate stays red until the contributor's branch is rebased

**Status:** needs a maintainer decision — not actioned
**Date:** 2026-10-01

The `CI Test Gate` workflow on `main` is fixed, but `pull_request` runs execute the
workflow file **from the head branch**, and fork PR #88 (`ahcrm-core`) still carries
the old `test-gate.yml` with `github-script@v7` and the vulnerable `${{ }}`
interpolation. Reruns keep failing at "Comment on PR", so that check stays red until
the branch picks up the fixed file.

**Why this was not just done:** pushing to a contributor's fork is a decision about
someone else's branch. Options:

1. Ask `ahcrm-core` to rebase onto `main` (cleanest, the branch stays theirs).
2. Push the workflow change to their fork directly (fastest, but writes to a third party's repo).
3. Leave the check red and treat it as informational until the contributor updates.

**Open question:** which option is the house policy for stale workflow files on
incoming forks.

## ci-test-gate: `sarif.py` has 0% test coverage

**Status:** DONE — covered, and a real bug found on the way
**Date:** 2026-10-01 (closed 2026-10-02)

`src/ci_test_gate/sarif.py` (16 statements) was never imported by any test, so the
`--output sarif` path of the CLI was entirely unexercised. Overall coverage was 89%.

Now covered by `tests/test_sarif_output.py`, both directly and end-to-end through
`suggest` and `local`. Writing those end-to-end tests exposed a real crash:
`local --output sarif` raised `AttributeError: 'list' object has no attribute
'source_paths'`, because the handler holds a plain `list[FileChange]` from
`DiffParser.parse()` but read it as a `Diff` model. Fixed in `cli.py` and
recorded in the CHANGELOG.

Coverage is now 99.61% (766/769) with `fail_under = 99` enforced in
`[tool.coverage.report]`. The remaining three statements are unreachable dead
code, documented in `pyproject.toml` rather than excluded with `# pragma: no cover`:
`cli.py:132`, `diff_parser.py:103` and `parser.py:29`.
## ci-test-gate: no lint gate; `cli.py` has a redundant local `subprocess` import

**Status:** DONE — both parts closed (lint gate wired, redundant import removed)
**Date:** 2026-10-03 (closed 2026-10-04)

Found by the repo-wide pyflakes scan (`F821,F811,F632`) run across every own repo,
the same scan that surfaced the `taintrace` annotation bug (PR #161).

`src/ci_test_gate/cli.py:137` re-imports `subprocess` inside `_handle_local()` even
though it is already imported at module scope (line 7). `F811`. Harmless at runtime —
Python resolves it to the same module — but it is dead code that misleads a reader
into thinking the handler has a subprocess-specific reason for the import.

**Why not just fixed here:** the repo is one commit behind `origin/main` and this run
had already spent both fronts (mcp-guard#86 workflow approval, taintrace#161). Also
worth confirming first whether `subprocess` at module scope is used anywhere else; if
it is only used by `_handle_local`, the fix is to delete the *module-level* import and
keep the local one, not the reverse.

**Closed 2026-10-04.** The open question is settled: the module-scope `subprocess`
import is used at five other call sites in `cli.py` (lines 141, 148, 158, 165, 171,
178), so the *local* import was the redundant one and it is the one that was deleted.
The gate now exists — `ruff.toml` with `select = ["F"]` plus a `lint` job in CI — and
it is verified to bite: a throwaway file with a duplicated test method made `ruff check`
exit 1 with `F811 Redefinition of unused`, which is exactly the defect this repo shipped
in `tests/test_cli.py` and never noticed.

Wiring the gate surfaced two more dead imports that the original `F821,F811,F632` scan
had missed because it never checked `F401`: `json` in `cli.py` and `DiffParser`/
`FileChange` in `classifier.py`. All three were fixed at the source, not exempted.

## ci-test-gate: style rules `E501`/`I001`/`UP037` are not enabled (47 findings)

**Status:** open — deliberately deferred
**Date:** 2026-10-04

`ruff check . --select=E501,I001,UP,B --statistics` reports **47** findings:
34 `E501` (line too long), 12 `I001` (unsorted imports), 1 `UP037` (quoted
annotation). No `B` findings. 13 of the 47 are auto-fixable (`--fix`); the
`E501` ones need `line-length` reviewed against the repo's existing style first.

**Why deferred:** the gate shipped narrow on purpose. A first gate that arrives
as a 47-line reformat gets disabled rather than fixed, which would be a worse
outcome than the one it replaced.

**Suggested follow-up:** run `ruff check . --select=I001,UP037 --fix` as its own
commit (13 findings, mechanical, zero risk), then decide `line-length` — the
repo has no declared value, so `ruff.toml` currently sets 100 — and pay `E501`
in a separate, reviewable commit. Widen `select` only once each of those is
green.

One concrete `I001` instance worth noting: `classifier.py` has two separate
`from .context_builder import ...` lines that ruff would merge and sort.
