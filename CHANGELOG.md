# Changelog

All notable changes to ci-test-gate will be documented in this file.

## [Unreleased]

## [0.1.3] - 2026-10-05

### Added
- **Verified Python 3.14 support.** `Programming Language :: Python :: 3.14`
  added to the classifiers and `'3.14'` added to the `test` job matrix in
  `.github/workflows/ci.yml`, keeping 3.10-3.13. `requires-python` already
  allowed it (`>=3.10`); what was missing was evidence and the classifier.

  The full suite passes on CPython 3.14.7 with no source change: **320 passed,
  13 warnings, 99.61% statement coverage** (gate floor 99.00%), against the
  same 320 passed / 99.61% on 3.13 -- identical test counts on both
  interpreters, so nothing is silently uncollected on 3.14. `ruff check .`
  is clean under 3.14. No test was skipped, xfailed or excluded to get there.

  This matters more than the usual version bump: 3.14 is the current stable
  release, and PyPI's version filter hides the package from anyone filtering
  by it, so the missing classifier made ci-test-gate invisible to new
  installs on today's Python.

### Tests
- **`tests/test_mkdocs_site_url.py::test_python_classifiers_match_the_ci_test_matrix`**
  asserts the `Programming Language :: Python :: X.Y` classifiers and the CI
  `python-version` matrix list the same set. The two drifted apart by default
  -- nothing compared them, which is how the matrix stopped at 3.13 while the
  interpreter moved on. Verified non-vacuous: reverting the matrix to four
  entries fails it with `advertised-only=['3.14']`.

### Fixed
- **`test-gate.yml` no longer interpolates `${{ }}` expressions into a shell
  line.** The `Fetch base ref from upstream` step expanded
  `github.event.pull_request.base.repo.full_name` and `...base.ref` straight into
  a `git fetch` command. The runner substitutes an expression *before* bash parses
  the line, so quoting it in the YAML would have protected nothing — the hostile
  text is already part of the script source when the shell sees it. Both values
  now travel through the step `env:` and are read as shell variables, which keeps
  the command line fixed regardless of what they contain. The fetch itself is
  unchanged: same URL, same ref, same `--depth=1`.

  Scoped honestly: for a valid pull request these two fields resolve to the
  **base** repository, which the maintainer controls — not the contributor's fork.
  Turning that into a working exploit needs write access to the base repo, so this
  is defence in depth rather than a critical hole. What it does remove is a
  standing trap: no future expansion in this file depends on the author
  remembering to quote correctly.

  Covered by `tests/test_fetch_step_template_injection.py`, which executes the
  step's real `run:` block under `bash` with hostile values substituted in, and
  asserts that no embedded command runs (the payload tries to plant a marker file)
  and that each value reaches `git` as a single argument.

## [0.1.2] - 2026-10-04

### Fixed
- **`Homepage` now points at the published documentation site**
  (`https://yunaremaia.github.io/ci-test-gate/`) instead of the bare repository,
  and **`Documentation`** now deep-links the first guide
  (`https://yunaremaia.github.io/ci-test-gate/getting-started/`) instead of
  repeating the site root. Both URLs were verified to return HTTP 200 before
  being written down.

  0.1.1 kept `Homepage` on the repository deliberately: "`Homepage` stays on the
  repository: no docs site is deployed, so a `Documentation` link would be
  dead." The `Documentation` entry it describes did land, but in commit `8d1a01c`
  — *after* the v0.1.1 tag — so the premise expired without the release
  noticing. PyPI is currently the only channel this project converts through,
  so the most prominent slot on the landing page was pointing at a README while
  a 26-page documentation site went unlinked.

  The repository is still linked, under `Source`, `Issues` and `Changelog`.

- **`tests/test_mkdocs_site_url.py` now guards both labels.** The existing test
  compared only `Documentation` against `mkdocs.yml`'s `site_url`, with a
  docstring stating that `Homepage` was "deliberately not compared". That left
  `Homepage` free to sit on the repository — precisely the field that shipped
  wrong. Both `Homepage` and `Documentation` must now sit under the published
  host, and the two must differ so one destination is not advertised twice.

### Added
- **Keywords expanded from 6 to 18**, each verified against the source rather
  than added on plausibility: `sarif` (`--output sarif`, `src/ci_test_gate/sarif.py`),
  `quality-gate` and `exit-codes` (gate mode exits 2 when a required test would
  be skipped), `github-action` (`.github/workflows/test-gate.yml`),
  `pull-request` (its input is a PR diff), `static-analysis` (the rule-based
  classifier and import/function extraction run without an LLM), `monorepo`
  (config-file changes widen selection "including inside subprojects and
  monorepo"), and one term per language the classifier actually recognises —
  `python`, `javascript`, `typescript`, `go`, `rust` (`docs/languages.md`).

  `coverage` remains deliberately absent, as in 0.1.1: this tool selects tests,
  it does not measure coverage, and the README says so.

- **Classifiers: 11 → 13.** Added `Operating System :: OS Independent`
  (confirmed by grepping `src/` for `sys.platform`, `os.name` and friends — the
  package is pure Python with no platform branching) and
  `Topic :: Software Development :: Version Control` (its input is a git diff
  and its output lands on a pull request or in an Actions job), which brings
  the set to parity with the sibling `diff-contract`.

- `__version__` bumped to 0.1.2 so `--version` does not report the previous
  release.

### Fixed (previously unreleased, shipped in 0.1.2)
- **BUG**: `tests/test_cli.py` defined two methods named `test_gate_mode_with_required_tests` in the same class. The second definition shadowed the first at class level, so the earlier body was never collected by pytest: an editor could change it and never see a test fail, and the coverage report gave no hint either. The two bodies were identical, so no behaviour was lost — but this is a test that silently stops running in a repo whose product is test selection. Collapsed into a single test, renamed `test_gate_mode_returns_zero_when_required_tests_are_covered` so the name states what it verifies. The exit-code-2 blocking path was already covered separately in `tests/test_cli_paths.py` and is untouched.
- **BUG**: `src/ci_test_gate/cli.py` re-imported `subprocess` inside `_handle_local()` although it is already imported at module scope. Removed the local import. (The module-scope import is required: five other call sites in the same module use it.)
- **BUG**: Two more dead imports found by the new lint gate and fixed at the source rather than exempted — `json` in `cli.py` (only ever used as a string literal such as `args.output == "json"`; output is serialised by `Recommendation.to_json()`) and `DiffParser`/`FileChange` in `classifier.py` (never referenced there, and nothing imports them from that module).

### Added
- **Lint gate.** `ruff.toml` with `select = ["F"]` (pyflakes) and a `lint` job in CI. Ruff is pinned in the `dev` extra so the local and CI versions match; rule selection lives in `ruff.toml` only, never in the workflow command.
- Unlike the sibling repos `taintrace` and `driftcheck`, which lint `src/` only so the gate can never pressure a change into weakening a test, this gate covers `tests/` too — the only real defect it has caught so far lived there. `F401` is exempted for `tests/*` only; `F811` and `F821` are enforced everywhere, since those are the rules that catch a test which shadows another or references something that does not exist.
- The dead-code line reference in the `pyproject.toml` coverage comment was updated from `cli.py:132` to `cli.py:131` after removing the imports shifted it.

## [0.1.1] - 2026-10-03

### Fixed
- **BUG**: `ci-test-gate local --output sarif` crashed with `AttributeError: 'list' object has no attribute 'source_paths'`. The handler treats `DiffParser.parse()` output as a plain list of `FileChange`, but read it as a `Diff` model. The changed-file list is now built directly and filtered to non-test files. Found by the new `--output sarif` tests; the `--output sarif` path of `local` had never been exercised.
- **BUG**: The CI Test Gate workflow failed on every pull request opened from a fork with `Resource not accessible by integration`. Fork runs get a read-only GITHUB_TOKEN, so the PR comment step could never succeed. The recommendation is now always written to the job summary, and only a 403 from the comment API is treated as non-fatal.
- **SECURITY**: The gate interpolated diff-derived text into the github-script body through a GitHub expression. A backtick in a fork PR's diff could break out of the template literal and execute arbitrary JavaScript in the runner. The report is now read from disk and passed via an environment variable.
- **BUG**: Gate mode logic was inverted — failed when no required tests existed and passed when required tests were missing. Now correctly returns exit code 2 only when required tests are NOT covered by the provided test files list. (#43)

### Added
- **Coverage gate.** `pyproject.toml` now sets `fail_under = 99` under `[tool.coverage.report]`, so coverage can no longer regress silently while CI stays green. The floor lives in the project config rather than a `--cov-fail-under` workflow flag so local runs and CI enforce the same number. Coverage goes from 89% (766/769 statements at 99.61%) with the gate at 99%. `precision = 2` is set because `should_fail_under` compares the total *rounded to whole percent* by default, which would let a real 98.5% satisfy a floor of 99. Three statements are unreachable dead code and are documented in place rather than excluded with `# pragma: no cover`: `cli.py:132` (`add_subparsers` is `required=True`, so `args.command` is always one of the two handled values), `diff_parser.py:103` (`line` is assigned from `raw_line.strip()` first, so it can never start with a space), and `parser.py:29` (the two-group header regex makes `re.split` always yield `3n+1` elements, so the loop never overruns).
- Test coverage for `sarif.py`, which had none — the `--output sarif` path of the CLI was entirely unexercised, as recorded in BACKLOG.md. The new tests cover the SARIF document skeleton, rule metadata, untested-changed-file reporting and JSON round-tripping, and drive the path end-to-end through both `suggest` and `local`.
- Tests for the remaining uncovered paths across the package: the `local` failure branches (diff body unreadable, test-file discovery failing), gate mode returning exit code 2, stdin input, the `__main__` entry point, `parse_from_git` against a real repository, LLM prompt construction and its fallback paths, and the `ContextBuilder` runner/import/function extraction branches.
- **Config-file changes now widen test selection.** A change to a project or dependency configuration file (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `requirements.txt`, `tsconfig.json`, lockfiles, and similar) is detected by basename — including inside subprojects and monorepos — and every known test is recommended instead of guessing from filenames. Tests that were directly modified or directly matched to a changed source file remain `required`; the rest become `recommended`. Both the rule-based fallback and the CLI classifier implement this. New `--config-changes {broad,normal}` flag on `suggest` and `local` controls it, defaulting to the conservative `broad`; it also applies in `--llm` mode. Pass `--config-changes normal` to restore the previous bounded broad set. Fixes #71.
- Test coverage for the CI Test Gate workflow itself. Both defects above lived entirely in `.github/workflows/test-gate.yml`, where the unit suite could not see them and no fork PR had yet exercised the fixed path. The new tests assert the workflow keeps reporting the recommendation to the job summary before the comment is attempted, treats only a 403 from the comment API as non-fatal, never interpolates diff-derived text into the script body, and rejects an empty gate report.
- A PyPI downloads badge in the README, linking to the project page.
- `Funding` added to `[project.urls]`; `Source` replaces `Repository`, so the
  repository URL is no longer advertised under two names, and the
  `test-impact-analysis` keyword was added. `coverage` was deliberately not
  added: the tool selects tests, it does not measure coverage.

## [0.1.0] - 2026-09-11

### Added
- Initial release: LLM-powered test selection for CI
- Multi-language support (Python, JS/TS, Go, Rust)
- Required/recommended/optional test classification
- GitHub Actions composite action
- Pre-commit hook support

### Added (2026-09-12)
- `.pre-commit-hooks.yaml` for native pre-commit integration
