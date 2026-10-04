# Language Support

`ci-test-gate` recognises test files by language. The classifier uses file
extension matching to associate source files with their corresponding tests.

## Supported Languages

### Python

Test patterns:
- `tests/test_*.py` — conventional pytest layout
- `test_*.py` — flat layout
- `*_test.py` — unittest convention

| Source | Test |
|--------|------|
| `src/app.py` | `tests/test_app.py` |
| `src/utils/helpers.py` | `tests/test_helpers.py` |
| `package/module.py` | `package/test_module.py` |

### JavaScript / TypeScript

Test patterns:
- `*.test.js`, `*.test.ts` — Jest, Vitest
- `*.spec.js`, `*.spec.ts` — Angular, older Jasmine
- `__tests__/*.js` — colocated tests

| Source | Test |
|--------|------|
| `src/app.ts` | `src/app.test.ts` |
| `src/components/Button.tsx` | `src/components/__tests__/Button.tsx` |
| `lib/utils.js` | `lib/utils.spec.js` |

### Go

Test pattern: `*_test.go`

Go uses a simple convention — test files are in the same package directory as source files.

| Source | Test |
|--------|------|
| `cmd/server.go` | `cmd/server_test.go` |
| `pkg/handler/user.go` | `pkg/handler/user_test.go` |

### Rust

Test patterns:
- `tests/*.rs` — integration tests
- `src/**/*.rs` inline `#[cfg(test)]` modules

| Source | Test |
|--------|------|
| `src/lib.rs` | `tests/integration.rs` |
| `src/handler.rs` | `src/handler.rs` (inline test mod) |

## Mixed-Language Example

Monorepo with multiple languages:

```yaml
# ci-test-gate.yml
languages:
  python:
    test_patterns: ["tests/test_*.py", "test_*.py"]
  javascript:
    test_patterns: ["*.test.js", "*.spec.js"]
  go:
    test_patterns: ["*_test.go"]
  rust:
    test_patterns: ["tests/*.rs"]

# Override auto-detection per path
overrides:
  path: "frontend/**"
  language: "javascript"
```

## File Extension Mapping

The classifier matches file extensions to ecosystems:

| Extension | Language |
|-----------|----------|
| `.py` | Python |
| `.js`, `.jsx` | JavaScript |
| `.ts`, `.tsx` | TypeScript |
| `.go` | Go |
| `.rs` | Rust |
| `.java` | Java |
| `.kt` | Kotlin |
| `.rb` | Ruby |
| `.php` | PHP |

---

## How matching actually works

Two implementation notes, because the tables above describe conventions while
the code does something simpler and more general.

**The match is on the reduced test name, not on a per-language pattern table.**
For each test path, `test_`, `_test.` and `tests/` are stripped, and the result
is substring-matched against each changed path. `tests/test_app.py` reduces to
`app.py`, so a change to `src/app.py` matches. There is no `*.test.ts` or
`*_test.go` rule being applied — those conventions are already covered, because
the reduced name of any of those files still contains the source name.

**Extension mapping feeds the LLM context, not the heuristic.** The
`detect_language()` table in `src/ci_test_gate/context.py` maps `.py`, `.js`,
`.jsx`, `.ts`, `.tsx`, `.rs`, `.go` and `.java` to a language, picks the majority
language of the diff, and attaches it to the prompt. Every other extension —
including `.kt`, `.rb` and `.php` — is `unknown`. The heuristic classifier is
language-agnostic and works from paths alone.

**The `ci-test-gate.yml` block above is not read by the current CLI.** There is
no `--config` flag and no config-file loader in `src/ci_test_gate/`;
configuration is CLI flags and environment variables only — see
[Configuration](configuration.md). The block is kept here as the intended shape
for per-language pattern overrides.

## Test discovery

The `local` command discovers tests itself, using fixed git pathspecs
regardless of language:

```bash
git ls-files 'tests/**' 'test/**' '*_test.py' '*.test.ts' '*.test.js'
```

For anything outside those patterns, pass an explicit list with
`suggest --test-files`.
