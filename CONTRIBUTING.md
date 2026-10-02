# Contributing to ci-test-gate

Thank you for your interest in contributing to ci-test-gate!

## Development Setup

**Requirements:**
- Python 3.10+
- pip or uv

**Setup:**

```bash
git clone https://github.com/yunaremaia/ci-test-gate.git
cd ci-test-gate
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest -q                              # run all tests
pytest tests/test_cli.py               # run specific test file
pytest -q --cov=ci_test_gate --cov-report=term-missing  # with coverage
pytest -q --no-cov tests/test_cli.py   # single file: skip the coverage gate
```

Note: `--cov` is set in `addopts`, so running a subset measures only part of the
package and will fail the `fail_under` floor. Use `--no-cov` when you run a single
test file outside CI.

## Project Structure

```
ci-test-gate/
├── src/ci_test_gate/
│   ├── classifier.py       # ML/NLP-based test classifier
│   ├── context_builder.py  # Build context from diffs
│   ├── context.py          # Context data structures
│   ├── diff_parser.py      # Parse git diffs
│   ├── cli.py              # CLI interface
│   ├── llm.py              # LLM integration for test selection
│   ├── models.py           # Data models
│   └── parser.py           # Input parsing
├── tests/                  # 17 test files, 99% coverage (gate: fail_under=99)
├── .github/workflows/      # CI/CD
└── pyproject.toml          # Build config
```

## Architecture

ci-test-gate uses an LLM-based pipeline:

1. **diff → context** — parse git diff and extract changed files/symbols
2. **context → classify** — use LLM to map changes to relevant tests
3. **classify → gate** — run only selected tests, skip irrelevant ones

This reduces CI time by 40-80% on large test suites by skipping tests unaffected by the changes.

## Code Style

- Formatter: `ruff format`
- Linter: `ruff check`
- Type hints: encouraged on all functions
- Test coverage: gated at 99% (`fail_under` in `pyproject.toml`) — a change that
  lowers coverage fails CI

## PR Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make your changes, add tests
4. Run tests: `pytest -q`
5. Commit, push, and open a PR
6. CI will run automatically

## Commit Messages

We follow Conventional Commits:
- `feat: add support for monorepo context`
- `fix: handle empty diff in classifier`
- `docs: update architecture section`
- `test: add coverage for LLM fallback`

## Reporting Issues

Use GitHub Issues. For bugs, include:
- Input diff that triggers the issue
- Expected vs actual behavior
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
