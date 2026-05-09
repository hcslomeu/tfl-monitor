# tests/

Pytest suite for the Python half of the codebase. Markers separate fast unit
tests from external-dependency-gated integration smokes.

## Layout

```text
tests/
├─ conftest.py            # Shared fixtures (FakeAsyncPool, FakeKafka, ...)
├─ test_contracts.py      # contracts/ drift + invariants
├─ test_health.py         # /health smoke
├─ agent/                 # Legacy agent observability (used by fixtures)
├─ airflow/               # Hermetic DAG-parse tests (marker: airflow)
├─ api/                   # Route handlers + OpenAPI drift + chat
├─ ingestion/             # tfl_client / producers / consumers
├─ rag/                   # fetch / parse / embed / upsert / ingest
├─ integration/           # External-dependency smokes (marker: integration)
└─ fixtures/              # JSON fixtures captured from the live TfL API
   └─ tfl/
```

## Markers

```toml
markers = [
    "integration: requires live services (Postgres, Kafka, etc.); opt in with -m integration",
    "airflow:     requires apache-airflow installed; opt in with -m airflow",
    "slow:        spends real LLM / RAG budget; opt in with -m 'integration and slow'",
]
```

Default invocation **excludes** `integration` and `airflow`:

```toml
addopts = "-m 'not integration and not airflow'"
```

## Running

```bash
uv run task test                              # default — fast unit suite
uv run pytest -m integration                  # external-deps smokes
uv run pytest -m airflow tests/airflow -v     # DAG parse
uv run pytest -m 'integration and slow'       # spends LLM budget
```

CI runs the default suite + frontend Vitest in parallel jobs.

## Test counts

| Suite | Unit | Integration | Notes |
|-------|------|-------------|-------|
| `api/` | ~50 | 14 | OpenAPI drift, all 6 endpoints, SSE chat, history |
| `ingestion/` | ~70 | 4 | Per-topic producer + consumer, retry, redaction |
| `rag/` | 28 | 0 | Fakes for httpx / Docling / OpenAI / Pinecone |
| `agent/` | (covered via `api/agent/`) | 3 | History round-trip + chat-stream + history-after-stream |
| `airflow/` | 4 | 0 | DAG-parse hermetic |
| `test_contracts.py` | parametrised | 0 | Pydantic-vs-DDL invariants |

## Fixtures

`conftest.py` exposes:

| Fixture | Purpose |
|---------|---------|
| `client` | FastAPI TestClient with overridable `app.state` |
| `FakeAsyncPool` | psycopg pool that returns predictable rows |
| `FakeKafka` | aiokafka stand-in (Producer + Consumer) |
| `monkey_settings` | Patches env-driven settings without touching `os.environ` |
| `tfl_fixtures` | Canonical TfL JSON payloads from `tests/fixtures/tfl/` |

The fixtures are deliberately **not** factory-style — they return concrete
shapes the tests can assert on. Rebuilding fixtures from the live API uses
[`scripts/fetch_tfl_samples.py`](../scripts/fetch_tfl_samples.py).

## Conventions

- **One assertion per test name.** A test called `test_returns_404_on_empty_window`
  asserts exactly that, not a four-line happy-path.
- **No live network.** Production code accepts client objects via constructor
  injection so fakes drop in without monkeypatching.
- **`-m 'integration and slow'` for LLM tests.** They cost real money — they
  should never run unless explicitly opted in.
