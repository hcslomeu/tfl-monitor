# tests/

Pytest suite for the Python half of the codebase. Markers separate fast unit
tests from external-dependency-gated integration smokes.

## Layout

```text
tests/
├─ conftest.py            # Shared fixtures (FakeTflClient, attach_agent, ...)
├─ test_contracts.py      # TfL fixtures validate against the tier-1 contracts
├─ test_health.py         # /health smoke
├─ agent/                 # compile_agent, tools, prompts
├─ api/                   # Route handlers, OpenAPI drift, SSE chat, CORS
├─ common/                # Logfire sampling options
├─ ingestion/             # tfl_client + disruption normaliser
├─ integration/           # Live-stack smoke (marker: integration)
└─ fixtures/              # JSON fixtures captured from the live TfL API
   └─ tfl/
```

## Markers

```toml
markers = [
    "integration: requires live services (TfL, Anthropic); opt in with -m integration",
    "slow: spends real LLM budget; opt in with -m 'integration and slow'",
]
```

Default invocation **excludes** `integration`:

```toml
addopts = "-m 'not integration'"
```

## Running

```bash
uv run task test                              # default: fast unit suite
uv run pytest -m 'integration and slow'       # live chat smoke, spends LLM budget
```

CI runs the default suite and the frontend Vitest suite in parallel jobs.

## Fixtures

`tests/conftest.py` exposes:

| Fixture | Purpose |
|---------|---------|
| `fake_tfl_client_factory` | Builds a `FakeTflClient` with canned line statuses, disruptions, and stop names |
| `attach_tfl_client` | Swaps `app.state.tfl_client` for the test and restores it |
| `attach_agent` | Swaps `app.state.agent` for the test and restores it |

`tests/agent/conftest.py` adds `FakeChatModel`, a deterministic chat model
for graph compile and invoke tests. Rebuilding the TfL JSON fixtures uses
[`scripts/fetch_tfl_samples.py`](../scripts/fetch_tfl_samples.py).

## Conventions

- **One behaviour per test name.**
- **No live network.** Production code accepts client objects via injection
  so fakes drop in without monkeypatching.
- **`-m 'integration and slow'` for LLM tests.** They cost real money and
  never run unless explicitly opted in.
