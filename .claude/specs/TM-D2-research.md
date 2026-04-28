# TM-D2 — Research (Phase 1)

Read-only investigation pass for **TM-D2: Wire status/reliability
endpoints to Postgres**. Output of this phase is a list of facts +
options + open questions. No design decisions are committed here;
those land in `TM-D2-plan.md` (Phase 2).

## 1. Charter

`PROGRESS.md` row + `SETUP.md` §7.4 table:

> TM-D2 — *Wire status/reliability endpoints to Postgres* — track
> `D-api-agent`, depends on TM-C2, phase 3.
> *Replace 501 stubs with real SQL against the mart layer.*

No detailed `.claude/specs/TM-D2-spec.md` exists. Acceptance criteria
are derived from:

- `contracts/openapi.yaml` (frozen tier-1 contract).
- The 501 stubs locked in `tests/api/test_stubs.py` carrying the
  `TM-D2` hint.
- Author's session-handover summary (latest snapshot semantics,
  parameterised SQL, Pydantic v2, OpenAPI drift test must keep
  passing, CORS allowlist preserved, pool cached on the app, Logfire
  psycopg instrumentation already wired).

## 2. Surface in scope

`tests/api/test_stubs.py::STUB_ROUTES` flags three routes with the
`TM-D2` WP hint — i.e. the 501 lock breaks for them as soon as TM-D2
lands. They are the surface area:

| Method | Path | OpenAPI operationId | Handler today |
|---|---|---|---|
| GET | `/api/v1/status/live` | `get_status_live` | `_not_implemented("Not implemented — see TM-D2")` |
| GET | `/api/v1/status/history` | `get_status_history` | same |
| GET | `/api/v1/reliability/{line_id}` | `get_line_reliability` | same |

Out of scope (still 501 after TM-D2):

- `/api/v1/disruptions/recent` → TM-D3
- `/api/v1/bus/{stop_id}/punctuality` → TM-D3
- `/api/v1/chat/stream`, `/api/v1/chat/{thread_id}/history` → TM-D5
- `/health` already implemented; `dependencies` payload stays empty
  for now (no plan to add a Postgres ping; revisit in TM-D5/TM-A5).

The session handover only listed `/status/live` + `/reliability/{line_id}`,
but `/status/history` is sibling 501 hint-keyed to TM-D2 and is part
of the same WP charter (status endpoints, plural). Phase 2 must
decide whether to deliver all three in one PR or split.

## 3. Response shapes (frozen)

From `contracts/openapi.yaml`:

### `LineStatus` (used by `/status/live` and `/status/history`)

| Field | Type | Notes |
|---|---|---|
| `line_id` | string | required |
| `line_name` | string | required |
| `mode` | enum string | `tube`, `elizabeth-line`, `overground`, `dlr`, `bus`, `national-rail`, `river-bus`, `cable-car`, `tram` |
| `status_severity` | int 0–20 | required |
| `status_severity_description` | string | required |
| `reason` | string \| null | nullable |
| `valid_from` | RFC3339 datetime | required |
| `valid_to` | RFC3339 datetime | required |

### `LineReliability` (used by `/reliability/{line_id}`)

| Field | Type | Notes |
|---|---|---|
| `line_id` | string | required |
| `line_name` | string | required |
| `mode` | string | required |
| `window_days` | int 1–90 | required |
| `reliability_percent` | number 0–100 | required, **non-nullable** |
| `sample_size` | int ≥ 0 | required |
| `severity_histogram` | object<string, int ≥ 0> | required |

### Query parameters

- `/status/history`: `line_id` (optional string), `from` (required
  RFC3339), `to` (required RFC3339).
- `/reliability/{line_id}`: `window` (optional int, **min 1, max 90,
  default 7**). The handover wrote `window_days`; the contract is
  `window`. Contract wins.
- `/status/live`: no query params.

Errors use RFC 7807 `application/problem+json` (already in the spec
under `components.responses.Problem`).

## 4. Data layer (already in `main`)

### Raw tables — `contracts/sql/001_raw_tables.sql`

```sql
CREATE TABLE raw.line_status (
    event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     JSONB NOT NULL
);
```

Indexes (`003_indexes.sql`):

- `idx_line_status_ingested_at` — BTREE on `ingested_at DESC`.
- `idx_line_status_payload_gin` — GIN on `payload`.

The producer normaliser (TM-B1/B2) flattens the TfL response into
`payload` keys exactly matching `LineStatus` fields above, so no
field renames are needed at the SQL boundary.

### dbt staging — `dbt/models/staging/stg_line_status.sql`

Incremental `merge` on `event_id`, 5-minute lookback, `on_schema_change=fail`.
Final `select` exposes typed columns one-to-one with the API schema:

```
event_id, ingested_at, event_type, source,
line_id, line_name, mode, status_severity, status_severity_description,
reason, valid_from, valid_to
```

### dbt mart — `dbt/models/marts/mart_tube_reliability_daily.sql`

Grain: `(line_id, calendar_date UTC, status_severity)`. Columns:

```
line_id, line_name, mode, calendar_date, status_severity,
status_severity_description, snapshot_count,
first_observed_at, last_observed_at, minutes_observed_estimate
```

`snapshot_count` is the multiplier needed to compute reliability.

### Reference table — `contracts/sql/002_reference_tables.sql`

`ref.lines (line_id, line_name, mode, colour_hex, loaded_at)` exists
but is **not populated** until TM-A2 / TM-B* CSV loaders run. Code
must not depend on `ref.lines` having rows.

## 5. App layer (already in `main`)

### `src/api/main.py`

- FastAPI app, version `0.0.1`.
- `CORSMiddleware` with explicit allowlist `["http://localhost:3000",
  "https://tfl-monitor.vercel.app"]` (TM-D1 hardened this).
- `/health` returns `{"status": "ok", "dependencies": {}}` synchronously.
- All TM-D2/D3/D5 routes raise `HTTPException(status_code=501,
  detail="Not implemented — see TM-XX")` via `_not_implemented()`.
- `response_model=None` is currently set on every stub. TM-D2 will
  **add** the proper `response_model=` for the three implemented
  routes.

### `src/api/observability.py`

Already calls `logfire.instrument_psycopg("psycopg")` and
`logfire.instrument_fastapi(app)`. No work needed; query spans will
appear once we make queries.

### Test scaffolding

- `tests/api/test_stubs.py` — parametrised 501 lock + bidirectional
  OpenAPI drift test. **It will fail when TM-D2 lands** because three
  routes will no longer return 501.
  - The `STUB_ROUTES` table needs to drop the three TM-D2 routes; the
    drift test (`test_every_app_route_declares_operation_id`,
    `test_spec_operation_ids_have_matching_routes`,
    `test_app_routes_have_matching_spec_entries`) must keep passing.
- `tests/integration/test_sql_init.py` — pattern for
  `@pytest.mark.integration` tests: `pytest.importorskip("psycopg")`,
  `pytest.mark.skipif(not DATABASE_URL, ...)`, sync `psycopg.connect`
  for assertions. **TM-D2 integration tests should mirror this
  pattern.**
- `tests/ingestion/conftest.py::FakeAsyncConnection` — async
  connection double if Phase 2 chooses unit tests over integration.

## 6. Dependencies — what's missing

`pyproject.toml` declares `psycopg[binary]>=3.2`. `uv.lock` resolves
to `psycopg==3.3.3`. **There is no `psycopg-pool` in the lock.** A
FastAPI route handler reusing a single `psycopg.AsyncConnection` is
not safe under concurrent requests (psycopg async connections
serialise; they are not coroutine-safe), so the implementation needs
either:

- **Option A:** Add `psycopg-pool>=3.2` (or `psycopg[binary,pool]`
  extra). `AsyncConnectionPool` provides per-request checkout.
- **Option B:** `asyncpg` instead of psycopg — rejected, breaks the
  Logfire psycopg instrumentation already wired in
  `src/api/observability.py` and `src/ingestion/observability.py`.
- **Option C:** Per-request `await psycopg.AsyncConnection.connect(...)`
  — works for a portfolio with low traffic, costs ~3-10 ms per
  request, breaks once the agent service starts hammering the API
  in TM-D5. Rejected for prod realism.

Recommendation for Phase 2: **Option A**. One line in
`pyproject.toml`, one shared pool created in a FastAPI lifespan,
`async with pool.connection() as conn` in handlers.

## 7. Live-status query — three options

The handover says *"latest snapshot per line — recommend
`stg_line_status` for snapshot grain"*. There are real trade-offs.

| Option | Source | Freshness | dbt-coupled | Complexity |
|---|---|---|---|---|
| A | `raw.line_status` + JSONB | <30 s (producer cadence) | no | medium (JSONB casts) |
| B | `stg_line_status` | as-of last `dbt run` | yes | low |
| C | Materialised view from staging | tunable | yes | high (extra DDL) |

Option B is what the handover suggests, but `stg_line_status` is a
dbt incremental table — it only contains rows up to the last `dbt
run`. Without TM-A2's Airflow nightly job in place, /status/live
could be hours stale. That defeats the "live" name.

Option A queries `raw.line_status` directly:

```sql
SELECT DISTINCT ON (payload->>'line_id')
       payload->>'line_id'                     AS line_id,
       payload->>'line_name'                   AS line_name,
       payload->>'mode'                        AS mode,
       (payload->>'status_severity')::int      AS status_severity,
       payload->>'status_severity_description' AS status_severity_description,
       NULLIF(payload->>'reason', '')          AS reason,
       (payload->>'valid_from')::timestamptz   AS valid_from,
       (payload->>'valid_to')::timestamptz     AS valid_to
FROM raw.line_status
WHERE event_type = 'line-status.snapshot'
  AND ingested_at >= now() - INTERVAL '15 minutes'  -- bound the scan
ORDER BY payload->>'line_id', ingested_at DESC;
```

The `ingested_at` window keeps the planner using
`idx_line_status_ingested_at`. Without it, Postgres could scan the
whole table.

Recommendation for Phase 2: **Option A**. "Live" must be live.
Document the 15-minute window guard as the freshness boundary
(if a line goes silent for >15 min it disappears — that itself is a
"degraded" signal; revisit after observing real producer behaviour).

## 8. History query

`/status/history` query params: `from` (required), `to` (required),
`line_id` (optional). Window is unbounded — a pathological caller
could ask for years.

Options for safety:

- **A:** Hard cap `to - from <= 30 days`; otherwise 400. Document in
  PR.
- **B:** Hard cap `LIMIT N` rows (e.g. 10 000); document.
- **C:** Both.

Option C is the realistic answer; A keeps SLA bounded, B is the last
line of defence. Recommend Phase 2 takes both.

Source: `stg_line_status` is the right grain (one row per snapshot,
typed columns). Lag from dbt is acceptable for a **history**
endpoint — historical data does not change. If the most recent
snapshots are missing because dbt has not run, that's documented
behaviour; users wanting freshest data hit `/status/live`.

## 9. Reliability query

`/reliability/{line_id}?window=N` (default 7, min 1, max 90 — from
the OpenAPI spec).

Source: `mart_tube_reliability_daily`. Grain is
`(line_id, calendar_date, status_severity)` so we group by `line_id`
+ filter by `calendar_date >= current_date - window` (UTC).

```sql
SELECT
    line_id,
    MIN(line_name)                           AS line_name,
    MIN(mode)                                AS mode,
    SUM(snapshot_count)::int                 AS sample_size,
    SUM(snapshot_count) FILTER (WHERE status_severity = 10)::numeric
        / NULLIF(SUM(snapshot_count), 0)
        * 100                                AS reliability_percent
FROM mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - %(window)s::int)
GROUP BY line_id;
```

Severity histogram is a separate query against the same mart:

```sql
SELECT status_severity, SUM(snapshot_count)::int AS count
FROM mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - %(window)s::int)
GROUP BY status_severity;
```

`severity_histogram` is shipped as `dict[str, int]` (key is the
severity number cast to string per the OpenAPI example
`{"6": 12, "9": 48, "10": 1956}`).

### 404 semantics

`reliability_percent` is required and non-nullable in the OpenAPI
schema. Two cases produce an "empty" result:

- The `line_id` is unknown to the warehouse (no rows ever).
- The `line_id` is known but the window is empty (e.g. line decommissioned).

Both are indistinguishable to the user. Options:

- **A:** Return `404` (RFC 7807 problem) when `sample_size = 0`.
- **B:** Return `200` with `reliability_percent = 0` and empty
  histogram. Loses the "no data" semantics.
- **C:** Add a `reliability_percent` nullable in OpenAPI — requires
  a contract change, ADR.

Recommend **A**: matches the OpenAPI `404` already declared, requires
no contract change, gives clear feedback. `404` body should say
*"No reliability data for line {line_id} in the last {window} days"*.

## 10. Pydantic response models

Two options for where to put them:

- **A:** `src/api/schemas.py` — fresh module, mirrors OpenAPI exactly.
- **B:** Reuse `contracts/schemas/line_status.py` — those are Kafka
  event payloads (`LineStatusPayload`), tier-2 schemas. Reuse would
  couple wire format to API response.

Recommend **A**. The boundary between Kafka payload and API response
is real; coupling them now would be the YAGNI mistake (we may want
to add API-only fields like `last_updated_observed_at`).

Naming: `LineStatusResponse`, `LineReliabilityResponse` to disambiguate
from the Kafka `LineStatusPayload`.

## 11. Pool wiring

FastAPI lifespan pattern:

```python
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool

@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.environ["DATABASE_URL"]
    async with AsyncConnectionPool(dsn, min_size=1, max_size=4, open=False) as pool:
        await pool.open()
        app.state.db_pool = pool
        yield

app = FastAPI(..., lifespan=lifespan)
```

Handler dependency:

```python
async def get_pool(request: Request) -> AsyncConnectionPool:
    return request.app.state.db_pool
```

Pool sizing (`min_size=1, max_size=4`) is conservative: a portfolio
single-instance FastAPI does not need more, and Supabase free tier
caps at 60 total connections. Phase 2 may want to make these env
configurable.

### Test-time DSN

`tests/api/test_stubs.py` builds a `TestClient(app)` which **runs the
lifespan**. Without a `DATABASE_URL`, lifespan startup will crash. Two
mitigations:

- **A:** In tests, monkeypatch `app.state.db_pool` and skip lifespan
  via `with TestClient(app, raise_server_exceptions=True) as c: ...`
  + a fixture that swaps in a fake pool.
- **B:** Make the pool optional; lifespan reads `DATABASE_URL`,
  no-op if unset. Handlers raise `503` if `app.state.db_pool` is
  `None`. Unit tests then exercise the 503 path; integration tests
  set the env and exercise the real path.

Recommend **B**. It mirrors the existing
`logfire.configure(send_to_logfire="if-token-present")` pattern (see
`src/api/observability.py`) — degrade gracefully without secrets.

## 12. Test strategy

Three tiers:

### Unit (default `uv run task test`)

- Parametrised SQL-shape assertions: handler builds the right
  `psycopg.sql.SQL` / `%(name)s` params for given inputs (especially
  `from`/`to`/`window`).
- Pydantic round-trip: rows from a `FakeAsyncConnection` materialise
  into `LineStatusResponse` / `LineReliabilityResponse` correctly.
- 404 path: empty result yields RFC 7807 problem with the right
  status + detail.
- 400 path: `from > to`, `window > 90`, `window < 1`,
  `to - from > 30d` all rejected with problem.
- CORS preflight still works (regression).

### Drift / contract (default)

- `tests/api/test_stubs.py` adjusted: drop the three implemented
  routes from `STUB_ROUTES`, but the bidirectional drift checks
  must still pass (now over the implemented routes too).

### Integration (`-m integration`, gated on `DATABASE_URL`)

- Spin up Postgres via `docker-compose` (already wired).
- Apply `contracts/sql/00*.sql` (already done by Compose init).
- Insert raw events directly into `raw.line_status` (skip Kafka,
  skip dbt). For `/reliability`, also insert directly into
  `mart_tube_reliability_daily` — bypass dbt for test speed; the dbt
  → mart contract is covered by dbt's own tests in TM-C2/TM-C3.
  Phase 2 must decide if this bypass is acceptable or whether a real
  `dbt run --select mart_tube_reliability_daily` is required.
- Hit endpoints via `TestClient(app)` after lifecycle starts the pool.
- Assert response shape + values.

## 13. Risks / surprises

1. **Lifespan changes break existing tests.** `tests/test_health.py`
   currently builds `TestClient(app)` without a database. If the
   lifespan unconditionally requires `DATABASE_URL`, that test fails.
   Mitigation: option B from §11.
2. **`test_stubs.py` will break.** The 501 lock parametrisation
   will fail for the three TM-D2 routes. The fix is intentional —
   but it must land **in the same PR** as the route implementations
   so the 501 lock keeps blocking unimplemented routes (TM-D3/TM-D5).
3. **`mart_tube_reliability_daily` is empty until line-status events
   ingest + dbt runs against them.** Integration tests must seed both
   the raw envelope and the mart, since the API queries the mart not
   the raw.
4. **`mart_tube_reliability_daily` includes EVERY mode**, not just
   tube. `mode` filtering is the caller's responsibility. The endpoint
   is `/reliability/{line_id}` — by line not by mode — so this is
   neutral, but worth flagging in the PR description.
5. **`status_severity_description` per `(line_id, day, severity)` may
   vary** if TfL changes the description for the same severity code
   mid-day (the mart uses `MIN(...)` to flatten). For
   `/status/live`, take the freshest row, so this is fine; for
   `/reliability/{line_id}` we don't return descriptions in the
   response, only the histogram codes — also fine. No risk from this
   for TM-D2.
6. **`bandit` may complain about psql connection string handling**
   if any code path logs the DSN. Easy mitigation: never log it.
7. **`mypy strict` + `psycopg-pool`.** Need to verify the pool stubs
   are typed; otherwise add a `[[tool.mypy.overrides]]` block. Check
   `psycopg_pool` typing during Phase 3.

## 14. Open questions for Phase 2

1. **Scope split.** One PR for all three endpoints (live + history +
   reliability) or split into TM-D2a (live + reliability — what the
   handover called out) and TM-D2b (history)? CLAUDE.md §"WP scope
   rules" says one WP, one PR — i.e. all three in one. **Lean: keep
   all three together unless the PR exceeds ~600 LoC.**
2. **dbt vs. raw for `/status/live`.** §7 above. Lean: query `raw`.
   Final call goes in plan.
3. **Window cap on `/status/history`.** §8. Lean: 30-day max +
   `LIMIT 10000`.
4. **Pool extra vs. separate dep.** `psycopg[binary,pool]` vs.
   `psycopg-pool`. Identical at runtime; the extra is more
   discoverable. Lean: extra.
5. **Optional `DATABASE_URL`.** §11. Lean: optional, 503 when missing.
6. **`reliability_percent` rounding.** OpenAPI says `number 0–100`,
   no precision constraint. Lean: 1 decimal (e.g. `94.2`) — matches
   the OpenAPI example.
7. **`severity_histogram` keys** as ints or strings? OpenAPI
   `additionalProperties: integer` over an object — JSON object keys
   are always strings. Lean: dict-cast `{str(k): int(v)}`.
8. **Integration tests vs dbt invocation.** §12.3. Lean: bypass dbt,
   seed mart directly; cover dbt → mart with dbt tests in TM-C2.
9. **Handler module layout.** Single `src/api/main.py` keeps growing.
   Options: split per-resource modules under `src/api/routes/`
   (`status.py`, `reliability.py`) and include via FastAPI router; or
   keep flat. CLAUDE.md §"Lean by default" leans flat for now —
   ~80 LoC of handlers is not enough to justify routers. Lean: keep
   flat.
10. **Connection pool size from env.** §11. Lean: hard-code
    `min=1, max=4` for now; expose env later if Supabase profiling
    shows hot-path saturation.
11. **`severity_histogram` density.** Should the response include
    severities with zero count in the window? Lean: no — only
    severities present in the window. Matches OpenAPI example shape.
12. **404 detail body.** RFC 7807 envelope or just `{"detail": "..."}`
    via FastAPI's default `HTTPException`? OpenAPI declares `Problem`
    schema. Lean: build problem-shaped responses for the new
    endpoints; don't retrofit `/health` or the still-501 stubs.

## 15. Acceptance criteria (proposed for Phase 2)

Working list — Phase 2 will lock these:

- [ ] `/api/v1/status/live` returns `LineStatus[]` ordered by
      `line_id`, latest snapshot per line, freshness window
      ≤ 15 min.
- [ ] `/api/v1/status/history` returns `LineStatus[]` filtered by
      `line_id` + `from`/`to` (UTC inclusive/exclusive),
      400 on invalid window, 30-day max window, `LIMIT 10 000`.
- [ ] `/api/v1/reliability/{line_id}` returns `LineReliability` for
      `window` (1–90, default 7); 404 when no data; histogram
      excludes zero-count severities.
- [ ] All SQL parameterised; no f-strings in queries; no string
      interpolation of caller input.
- [ ] `psycopg-pool` (or `psycopg[binary,pool]` extra) added; pool
      created on FastAPI lifespan, cached on `app.state.db_pool`,
      `min_size=1, max_size=4`.
- [ ] Pool is optional: lifespan no-ops when `DATABASE_URL` is
      missing, handlers return 503 in that case (mirrors Logfire's
      `if-token-present`).
- [ ] CORS allowlist preserved (no widening).
- [ ] OpenAPI drift test still passes (the bidirectional checks
      remain green).
- [ ] `tests/api/test_stubs.py` 501 lock dropped for the three TM-D2
      routes; the rest still 501.
- [ ] Pydantic v2 response models in `src/api/schemas.py`.
- [ ] Integration tests under `tests/integration/test_status_*.py`
      and `tests/integration/test_reliability_*.py`, gated on
      `DATABASE_URL`.
- [ ] `uv run task lint` (ruff + ruff format + mypy strict) green.
- [ ] `uv run task test` (default, hermetic) green.
- [ ] `uv run bandit -r src --severity-level high` reports no findings.
- [ ] `make check` green end-to-end.
- [ ] `PROGRESS.md` TM-D2 row marked ✅ with completion date.
- [ ] PR title `feat(api): TM-D2 wire status + reliability to Postgres (TM-10)`,
      body closes Linear `TM-10`.

## 16. Files expected to change in Phase 3

Authoritative-list (subject to plan refinement):

- `pyproject.toml` — add `psycopg[binary,pool]` extra (or
  `psycopg-pool`).
- `uv.lock` — regenerated.
- `src/api/main.py` — lifespan, real handlers for the three routes,
  `response_model=` set, imports.
- `src/api/schemas.py` (new) — `LineStatusResponse`,
  `LineReliabilityResponse`, `Problem` if needed.
- `src/api/db.py` (new) — pool factory, `get_pool` dependency, query
  helpers (so SQL stays out of `main.py`).
- `tests/api/test_stubs.py` — drop the three routes from
  `STUB_ROUTES`.
- `tests/api/test_status_live.py` (new) — unit.
- `tests/api/test_status_history.py` (new) — unit.
- `tests/api/test_reliability.py` (new) — unit.
- `tests/integration/test_status_live.py` (new) — integration.
- `tests/integration/test_status_history.py` (new) — integration.
- `tests/integration/test_reliability.py` (new) — integration.
- `tests/conftest.py` (new at root) — shared fixture for the FakeAsyncPool
  used by API unit tests.
- `PROGRESS.md` — flip the row to ✅.

No changes to:

- `contracts/openapi.yaml` (frozen).
- `contracts/schemas/*` (Kafka tier — out of scope).
- `dbt/` (mart already in main).
- `web/` (E1b is the next WP, not D2).
- `Makefile` (no new orchestration needed).
