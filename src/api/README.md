# src/api/

FastAPI application: live TfL status and disruption endpoints, an SSE chat
stream, a LangGraph agent compiled at startup, and OpenAPI 3.1 as the
contract. Deployed as a stateless Vercel Python function (ADR 015).

## Layout

```text
src/api/
├─ __init__.py
├─ main.py             # FastAPI app, lifespan, route handlers (Vercel entrypoint)
├─ live.py             # Live TfL read-through (status + disruptions)
├─ stations.py         # NaPTAN ↔ name resolver over cached TfL lookups
├─ schemas.py          # Pydantic response models (mirror contracts/openapi.yaml)
├─ observability.py    # Logfire wiring (FastAPI only; sampled)
├─ debug_tfl.py        # Local-only Swagger proxy to raw TfL payloads
└─ agent/              # LangGraph agent, see src/api/agent/README.md
```

## Lifespan

The lifespan opens one `TflClient` (when `TFL_APP_KEY` is set) and compiles
the agent (when `ANTHROPIC_API_KEY` is set). Every route that needs a missing
dependency returns RFC 7807 `503` instead of crashing, so `/health` works
without secrets.

## Endpoints

| Method | Path | Source |
|--------|------|--------|
| `GET`  | `/health` | static |
| `GET`  | `/api/v1/status/live` | TfL `/Line/Mode/{modes}/Status` (live, CDN-cached 30 s) |
| `GET`  | `/api/v1/disruptions/recent` | TfL `/Status?detail=true` (live, CDN-cached 30 s) |
| `POST` | `/api/v1/chat/stream` | LangGraph agent (SSE) |

The two GET endpoints send `Cache-Control: public, s-maxage=30,
stale-while-revalidate=30`, so the Vercel CDN serves every dashboard
viewer's polling from at most one function run per window. Every error is
`application/problem+json` (RFC 7807).

## OpenAPI invariants

`tests/api/test_stubs.py` checks both directions between
`contracts/openapi.yaml` and the routes FastAPI registers; drift fails CI.

## Observability

`instrument_fastapi` emits one span per request, sampled with the shared
`SamplingOptions.level_or_duration` strategy from `src/common/sampling.py`:
warn+ spans and traces longer than five seconds are kept at 100%,
everything else falls back to `LOGFIRE_SAMPLE_RATE` (default `0.1`).
LLM and tool-call visibility lives in LangSmith.

## Run

```bash
make api                              # uvicorn with .env loaded
curl http://localhost:8000/health
curl -N -X POST http://localhost:8000/api/v1/chat/stream \
  -H 'content-type: application/json' \
  -d '{"thread_id":"smoke","message":"Is the Piccadilly line running normally right now?"}'
```
