# ci-test-gate

[![CI](https://github.com/yunaremaia/ci-test-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/yunaremaia/ci-test-gate/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yunaremaia/ci-test-gate/branch/main/graph/badge.svg)](https://codecov.io/gh/yunaremaia/ci-test-gate)

**LLM-powered test selection for CI — run only the tests that matter.**

Tired of waiting 30+ minutes for CI when your change touches one file? `ci-test-gate` analyzes your PR diff and recommends which tests to run, skip, or require.

```bash
pip install git+https://github.com/yunaremaia/ci-test-gate.git
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

### License

MIT

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing guidelines, and how to add a new classifier.
