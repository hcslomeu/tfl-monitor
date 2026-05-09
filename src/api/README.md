# src/api/

FastAPI application — six warehouse-backed endpoints, an SSE chat stream, a
LangGraph agent compiled at startup, and OpenAPI 3.1 as the contract.

## Layout

```text
src/api/
├─ __init__.py
├─ main.py             # FastAPI app, lifespan, route handlers
├─ db.py               # Async psycopg pool + per-endpoint fetchers
├─ schemas.py          # Pydantic response models (mirror contracts/openapi.yaml)
├─ observability.py    # Logfire wiring (FastAPI / psycopg / httpx)
└─ agent/              # LangGraph agent — see src/api/agent/README.md
```

## Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if database_url := os.environ.get("DATABASE_URL"):
        app.state.pool = AsyncConnectionPool(database_url, min_size=1, max_size=4)
        await app.state.pool.open()
    else:
        app.state.pool = None

    app.state.agent = compile_agent()  # None if any of 3 keys missing
    yield
    if app.state.pool:
        await app.state.pool.close()
```

So the app boots and serves a meaningful subset of routes whether or not the
database / LLM credentials are set — every route that needs a missing
dependency returns RFC 7807 `503` instead of crashing.

## Endpoints

| Method | Path | Source |
|--------|------|--------|
| `GET`  | `/health` | static |
| `GET`  | `/api/v1/status/live` | `raw.line_status` (15-min freshness) |
| `GET`  | `/api/v1/status/history` | `analytics.stg_line_status` (30-day cap) |
| `GET`  | `/api/v1/reliability/{line_id}` | `analytics.mart_tube_reliability_daily` |
| `GET`  | `/api/v1/disruptions/recent` | `analytics.stg_disruptions` |
| `GET`  | `/api/v1/bus/{stop_id}/punctuality` | `analytics.stg_arrivals` |
| `POST` | `/api/v1/chat/stream` | LangGraph agent (SSE) |
| `GET`  | `/api/v1/chat/{thread_id}/history` | `analytics.chat_messages` |

Every error is `application/problem+json` (RFC 7807) — see the
[FastAPI surface](../../docs/pipelines/api.md) doc.

## OpenAPI invariants

CI runs a bidirectional drift test between `contracts/openapi.yaml` and the
OpenAPI emitted by FastAPI at startup — drift in either direction fails the
test in `tests/api/test_openapi_drift.py`.

## Observability

Three lines in `observability.py`:

```python
logfire.instrument_fastapi(app)
logfire.instrument_psycopg()
logfire.instrument_httpx()
```

This auto-emits one span per request, query, and outbound HTTP call. Token
costs and tool decisions land in LangSmith via the agent — see
[`src/api/agent/README.md`](./agent).

## Run

```bash
uv run task api                       # uvicorn api.main:app --reload --app-dir src
```

Health check:

```bash
curl http://localhost:8000/health
```

Smoke against `/chat/stream` (requires the three LLM-side keys):

```bash
curl -N -X POST http://localhost:8000/api/v1/chat/stream \
  -H 'content-type: application/json' \
  -d '{"thread_id":"smoke","message":"Which Tube line had the worst reliability last week?"}'
```
