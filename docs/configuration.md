# Configuration

`ci-test-gate` has no config file. Every knob is a CLI flag, and the two that
also read the environment are the LLM settings.

## Config file changes (`--config-changes`)

The one flag with real consequences for how many tests you run. Full output
examples are in [Usage → Config file changes](usage.md#config-file-changes).

| Value | Behaviour |
|---|---|
| `broad` (default) | When a recognised project/dependency config file changes, recommend **every** test you supplied. Directly matched tests stay `required`, the rest become `recommended`. |
| `normal` | Ordinary path-based matching, config files treated like any other file. |

```bash
ci-test-gate suggest --diff pr.diff --test-files tests.txt --config-changes broad
```

The recognised basenames are listed in
[Usage → Config file changes](usage.md#which-files-count-as-config-files). They
are matched on basename, so `services/api/package.json` and
`monorepo/crates/inner/Cargo.toml` both count.

## LLM mode

Pass `--llm` to `suggest` or `local` to classify with an OpenAI-compatible
model instead of the built-in heuristic.

```bash
ci-test-gate suggest --diff pr.diff --test-files tests.txt --llm
```

| Setting | Flag | Environment variable | Default |
|---|---|---|---|
| Enable | `--llm` | — | off |
| API key | `--llm-api-key` | `OPENAI_API_KEY` | — |
| Model | `--llm-model` | `CI_TEST_GATE_MODEL` | `gpt-4o-mini` |
| Base URL | — | `OPENAI_BASE_URL` | `https://api.openai.com/v1` |

CLI flags take precedence over environment variables. There is no flag for the
base URL — set `OPENAI_BASE_URL` to target a local or self-hosted
OpenAI-compatible endpoint.

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="http://localhost:11434/v1"

ci-test-gate suggest \
  --diff pr.diff \
  --test-files tests.txt \
  --llm \
  --llm-model gpt-4o \
  --output json
```

## Fallback behaviour

If no API key is configured, or the LLM call fails for any reason — network
error, rate limit, malformed response — `ci-test-gate` falls back to the
heuristic classifier rather than failing. Your CI pipeline is never blocked by
the LLM path.

```console
$ ci-test-gate suggest --diff pr.diff --test-files tests.txt --llm   # no API key
## ci-test-gate Recommendation

**Reasoning:** Heuristic match: 1 required test(s) from 1 changed file(s).
...
```

The `--config-changes` setting applies in `--llm` mode as well.

## What is not configurable

- **Test naming patterns.** The heuristic reduces each test path to a base name
  by stripping `test_`, `_test.` and `tests/` and then substring-matching it
  against the changed paths. There is no way to add or override a pattern.
- **The savings estimate.** `estimated_savings_pct` is computed from test
  counts, capped at 95%. It is not configurable and not measured.
- **Classifier selection by name.** `TestClassifier.from_config()` accepts
  `classifier_type` of `heuristic` or `llm` as a Python API detail; the CLI
  exposes it only as the presence or absence of `--llm`.

## Language detection

The primary language of a diff is inferred from file extensions
(`src/ci_test_gate/context.py`), and it feeds the LLM context only. The
heuristic path is name-based and language-agnostic. Recognised extensions:

| Extension | Language |
|---|---|
| `.py` | Python |
| `.js`, `.jsx` | JavaScript |
| `.ts`, `.tsx` | TypeScript |
| `.rs` | Rust |
| `.go` | Go |
| `.java` | Java |

Anything else is `unknown`. See [Language Support](languages.md) for the test
naming conventions the classifier recognises.
