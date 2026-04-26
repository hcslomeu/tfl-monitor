# TM-D1 — Research (Phase 1)

Read-only exploration. Track: **D-api-agent**. Linear issue: **TM-6** (open).

Objective from `SETUP.md` §7.3: "Stand up FastAPI with all endpoints returning 501 and Logfire configured."

## Scope boundary

Allowed paths: `src/api/`, plus the paired test file(s) under `tests/`.
Forbidden without ADR: `contracts/openapi.yaml` (any drift → ADR per
AGENTS.md §2).

## What already exists (delivered by TM-000)

### API skeleton — `src/api/main.py`

| Route | Method | OpenAPI `operationId` | Current body | Target WP |
|---|---|---|---|---|
| `/health` | GET | `get_health` | Returns `{"status":"ok","dependencies":{}}` | TM-D1 (this) |
| `/api/v1/status/live` | GET | `get_status_live` | `501` → `"Not implemented — see TM-D2"` | TM-D2 |
| `/api/v1/status/history` | GET | `get_status_history` | `501` → `"Not implemented — see TM-D2"` | TM-D2 |
| `/api/v1/reliability/{line_id}` | GET | `get_line_reliability` | `501` → `"Not implemented — see TM-D2"` | TM-D2 |
| `/api/v1/disruptions/recent` | GET | `get_recent_disruptions` | `501` → `"Not implemented — see TM-D3"` | TM-D3 |
| `/api/v1/bus/{stop_id}/punctuality` | GET | `get_bus_punctuality` | `501` → `"Not implemented — see TM-D3"` | TM-D3 |
| `/api/v1/chat/stream` | POST | `post_chat_stream` | `501` → `"Not implemented — see TM-D5"` | TM-D5 |
| `/api/v1/chat/{thread_id}/history` | GET | `get_chat_history` | `501` → `"Not implemented — see TM-D5"` | TM-D5 |

All 8 routes declared in `contracts/openapi.yaml` have matching handlers
with matching `operation_id`s. `501` helper is centralised via
`_not_implemented(detail)`. CORS is an explicit allow-list:

```python
CORSMiddleware(
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

CORS uses an explicit allow-list (no wildcard `*`), which satisfies the
"no `*` in production" rule from CLAUDE.md §"Security-first". **However,
the list currently contains only `http://localhost:3000`** and is
missing the production Vercel origin documented at
`contracts/openapi.yaml` lines 12–13 (`https://tfl-monitor.vercel.app`).
That gap would block all production dashboard requests and is treated
as a deployment blocker in the gap analysis below (G4).

### Logfire wiring — `src/api/observability.py`

`configure_observability(app)` — one function, called once from `main.py`:

```python
logfire.configure(
    service_name="tfl-monitor-api",
    service_version=os.getenv("APP_VERSION", "0.0.1"),
    environment=os.getenv("ENVIRONMENT", "local"),
    send_to_logfire="if-token-present",
)
logfire.instrument_fastapi(app)
logfire.instrument_httpx()
logfire.instrument_psycopg("psycopg")
```

Matches CLAUDE.md §"Observability architecture" word-for-word plus the
additional `instrument_httpx()` (needed when we wire outgoing HTTP from
the agent in TM-D5). `send_to_logfire="if-token-present"` makes the
call a no-op in CI / local-without-token — no extra guards required.

`logfire[fastapi,httpx,psycopg]>=3.0` is in `pyproject.toml` deps.

### Dependencies and tests

- `pyproject.toml`: `fastapi>=0.115`, `uvicorn[standard]>=0.32`,
  `sse-starlette>=2.1`, `httpx>=0.28`, `pydantic>=2.9`,
  `pydantic-settings>=2.6`, `logfire[fastapi,httpx,psycopg]>=3.0`.
- Taskipy: `api = "uvicorn api.main:app --reload --app-dir src"`.
- `tests/test_health.py` — one smoke test: `GET /health` → 200.
- `tests/test_contracts.py` — covers Pydantic tier-1/tier-2 contracts
  for Kafka events; does **not** assert anything about API routes.

### CI coverage

`.github/workflows/ci.yml`:
- Lint job runs `uv run task lint` (mypy strict on `src/` includes
  `src/api/`) and `uv run bandit -r src contracts scripts`.
- Test job runs `uv run task test` → Pytest → covers `test_health.py`.
- Frontend job runs `openapi-typescript contracts/openapi.yaml`
  diff-gated so the OpenAPI spec cannot drift from the TS types.

## Current state verification

Nothing to run here — `main.py` is already the "501-stubs + health"
skeleton the spec asks for, and `observability.py` already exposes the
required Logfire surface.

## Gap analysis — what remains for TM-D1

| # | Item | Value | Cost |
|---|---|---|---|
| G1 | Parametrised test `tests/api/test_stubs.py` asserting every non-`/health` route returns 501 with the documented hint | Locks the spec (cannot accidentally ship a half-wired route before its owning WP) | ~30 lines pytest; adds `tests/api/` folder |
| G2 | Test asserting every `operationId` in `contracts/openapi.yaml` has a matching FastAPI route (drift detector) | Catches silent route loss | ~40 lines; uses `yaml` + `app.routes` |
| G3 | Document `/health` shape in a `src/api/README.md` or extend docstring | Portfolio-optics; explain why `dependencies` is `{}` until TM-D2 | docs only |
| G4 | **Deployment blocker** — extend CORS allow-list to include the Vercel prod origin (`https://tfl-monitor.vercel.app`) so the production dashboard can reach the API | Without this, all prod requests fail CORS preflight; the openapi.yaml info block (lines 12–13) already declares this origin as in-scope | 1 line change |
| G5 | Ship a `get_health` dependency-check scaffold (empty dict today) | Shape-only; actual DB/Kafka checks land in TM-D2/TM-B3 | `health.py` helper |
| G6 | Add an `api/config.py` Pydantic `Settings` — not yet required (no env vars consumed outside observability) | YAGNI per CLAUDE.md rule 5 (< 15 vars) | defer |
| G7 | Ensure `src/api/__init__.py` is valid (empty file today) | Neutral | no action |

G1 and G2 give the WP something concrete to ship. **G4 is reclassified
as P0/critical — a real production blocker, not optional polish** (the
openapi.yaml spec already declares the missing origin). G3 is optional
polish. G5/G6/G7 are YAGNI.

## Key documents reviewed

- `src/api/main.py`, `src/api/observability.py`, `src/api/__init__.py`.
- `contracts/openapi.yaml` (full read).
- `tests/test_health.py`, `tests/test_contracts.py`.
- `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`.
- `CLAUDE.md` §"Observability architecture", §"Security-first".
- `AGENTS.md` §"PR rules — Observability", §"Security (blockers)".

## Open questions for the planning phase

1. **Headline question — RESOLVED on 2026-04-23.** The spec's declared
   AC from `SETUP.md` §7.3 ("skeleton + 501 + Logfire configured") is
   already satisfied by TM-000, but G4 is a deployment blocker (CORS
   omits the production Vercel origin). Author chose option **(a)**:
   ship G1 + G2 + G4 as the concrete deliverable in TM-D1. Option (b)
   "close as already-delivered" was rejected because deferring G4 to
   TM-A5 (deploy) would push a known production blocker out of the
   security/API track that owns it.
2. G2 implementation — confirmed: use the loader bundled with
   `openapi-spec-validator` (already a dev dep). No new runtime
   dependency; if `pyyaml` is needed, add it only to the `dev` group
   and justify in the PR body.
