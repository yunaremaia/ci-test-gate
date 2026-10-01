# ci-test-gate

[![CI](https://github.com/yunaremaia/ci-test-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/yunaremaia/ci-test-gate/actions/workflows/ci.yml) ![py](https://img.shields.io/badge/python-3.10-blue.svg) [![PyPI](https://img.shields.io/pypi/v/ci-test-gate)](https://pypi.org/project/ci-test-gate/) ![license](https://img.shields.io/github/license/yunaremaia/ci-test-gate) ![release](https://img.shields.io/github/v/release/yunaremaia/ci-test-gate) ![stars](https://img.shields.io/github/stars/yunaremaia/ci-test-gate)
[![codecov](https://codecov.io/gh/yunaremaia/ci-test-gate/branch/main/graph/badge.svg)](https://codecov.io/gh/yunaremaia/ci-test-gate)

**LLM-powered test selection for CI — run only the tests that matter.**

Tired of waiting 30+ minutes for CI when your change touches one file? `ci-test-gate` analyzes your PR diff and recommends which tests to run, skip, or require.

### Installation

`ci-test-gate` is published on [PyPI](https://pypi.org/project/ci-test-gate/):

```bash
pip install ci-test-gate
```

To follow the tip of `main` instead of the latest release, install straight from the repository:

```bash
pip install git+https://github.com/yunaremaia/ci-test-gate.git
```

### Quickstart

```bash
ci-test-gate suggest --diff pr.diff --test-files tests.txt
```

### How it works

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
│  │  4. Output recommendation (JSON/Markdown) │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

### Why?

- **Save CI minutes** — skip irrelevant tests
- **Faster feedback** — required tests run first
- **Risk-aware** — conservative by default
- **Multi-language** — Python, JS/TS, Go, Rust

See [docs/LANGUAGES.md](docs/LANGUAGES.md) for language-specific test pattern documentation.

### Modes

- `suggest` — Comment on PR with recommendations
- `gate` — Block merge if required tests didn't run
- `local` — Run before push to catch issues early

### Config file changes

A change to a project or dependency configuration file — `pyproject.toml`,
`package.json`, `Cargo.toml`, `go.mod`, `requirements.txt`, `tsconfig.json`,
their lockfiles, and similar — can break any test in the repository, not just
tests whose name resembles the changed file. Matching by filename in that case
under-selects, which is the more dangerous failure for a test gate.

By default, when any such file changes, `ci-test-gate` recommends **every**
test it knows about. Tests that were directly modified or directly matched to
a changed source file remain `required`; the rest are `recommended`.

```console
$ ci-test-gate suggest --diff pr.diff --test-files tests.txt
```

To restore ordinary path-based matching, pass `--config-changes normal`:

```console
$ ci-test-gate suggest --diff pr.diff --test-files tests.txt --config-changes normal
```

The flag is available on both `suggest` and `local`, and also applies in
`--llm` mode. Detection matches the basename, so configuration inside
subprojects and monorepos (`services/api/package.json`) counts too.

> This depends on the accuracy of your test-file list: a test that was never
> passed in via `--test-files` (or discovered by `local`) cannot be recommended.
> The widening is deliberately conservative — it never omits a known test for a
> configuration change — but it does not measure real coverage, and it cannot
> prove that any selected suite exercises the changed dependency.

---

## LLM Classification

`ci-test-gate` supports LLM-powered semantic classification in addition to the built-in heuristic engine.
When enabled, it sends the diff context to an OpenAI-compatible API and lets the model reason about which tests are most likely affected.

### Enabling LLM mode

Pass `--llm` to the `suggest` or `local` command:

```bash
ci-test-gate suggest --diff pr.diff --test-files tests.txt --llm
```

### Configuration

| CLI flag | Environment variable | Default | Description |
|---|---|---|---|
| `--llm` | — | off | Enable LLM classification |
| `--llm-api-key` | `OPENAI_API_KEY` | — | API key for the OpenAI-compatible endpoint |
| `--llm-model` | `CI_TEST_GATE_MODEL` | `gpt-4o-mini` | Model to use |
| — | `OPENAI_BASE_URL` | OpenAI production | Base URL (for local/alternative endpoints) |

CLI flags take precedence over environment variables.

### Example — using a custom model

```bash
export OPENAI_API_KEY="sk-..."
ci-test-gate suggest \
  --diff pr.diff \
  --test-files tests.txt \
  --llm \
  --llm-model gpt-4o \
  --output json
```

### Fallback behaviour

If no API key is configured, or if the LLM call fails for any reason (network error, rate limit, malformed response), `ci-test-gate` automatically falls back to the heuristic classifier so your CI pipeline is never blocked.

---

### Roadmap

- [x] LLM semantic classification (v0.2.0)
- [ ] Gate mode enforcement (v0.2.0)
- [ ] Dashboard with savings metrics (v0.4.0)

If this tool is useful to you, a star helps other people find it.

## Related tools

- **[diff-contract](https://github.com/yunaremaia/diff-contract)** — lock API contracts with diff-based tests
- **[ci-sandbox](https://github.com/yunaremaia/ci-sandbox)** — sandbox untrusted CI steps
- **[vibeguard](https://github.com/yunaremaia/vibeguard)** — guardrails for AI-generated code changes
- **[mcp-guard](https://github.com/yunaremaia/mcp-guard)** — audit MCP servers for unsafe permissions

Part of a family of focused, single-purpose developer tools — each one does one thing
and does it well.

### License

MIT

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing guidelines, and how to add a new classifier.

