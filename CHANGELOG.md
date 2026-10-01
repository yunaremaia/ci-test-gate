# Changelog

All notable changes to ci-test-gate will be documented in this file.

## [Unreleased]

### Fixed
- **BUG**: The CI Test Gate workflow failed on every pull request opened from a fork with `Resource not accessible by integration`. Fork runs get a read-only GITHUB_TOKEN, so the PR comment step could never succeed. The recommendation is now always written to the job summary, and only a 403 from the comment API is treated as non-fatal.
- **SECURITY**: The gate interpolated diff-derived text into the github-script body through a GitHub expression. A backtick in a fork PR's diff could break out of the template literal and execute arbitrary JavaScript in the runner. The report is now read from disk and passed via an environment variable.
- **BUG**: Gate mode logic was inverted — failed when no required tests existed and passed when required tests were missing. Now correctly returns exit code 2 only when required tests are NOT covered by the provided test files list. (#43)

### Added
- **Config-file changes now widen test selection.** A change to a project or dependency configuration file (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `requirements.txt`, `tsconfig.json`, lockfiles, and similar) is detected by basename — including inside subprojects and monorepos — and every known test is recommended instead of guessing from filenames. Tests that were directly modified or directly matched to a changed source file remain `required`; the rest become `recommended`. Both the rule-based fallback and the CLI classifier implement this. New `--config-changes {broad,normal}` flag on `suggest` and `local` controls it, defaulting to the conservative `broad`; it also applies in `--llm` mode. Pass `--config-changes normal` to restore the previous bounded broad set. Fixes #71.
- Test coverage for the CI Test Gate workflow itself. Both defects above lived entirely in `.github/workflows/test-gate.yml`, where the unit suite could not see them and no fork PR had yet exercised the fixed path. The new tests assert the workflow keeps reporting the recommendation to the job summary before the comment is attempted, treats only a 403 from the comment API as non-fatal, never interpolates diff-derived text into the script body, and rejects an empty gate report.

## [0.1.0] - 2026-09-11

### Added
- Initial release: LLM-powered test selection for CI
- Multi-language support (Python, JS/TS, Go, Rust)
- Required/recommended/optional test classification
- GitHub Actions composite action
- Pre-commit hook support

### Added (2026-09-12)
- `.pre-commit-hooks.yaml` for native pre-commit integration
