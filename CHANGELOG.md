# Changelog

All notable changes to ci-test-gate will be documented in this file.

## [Unreleased]

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
