# TM-D2 — Plan (Phase 2)

Implementation plan for **TM-D2: Wire status/reliability endpoints to
Postgres**. Built from `.claude/specs/TM-D2-research.md`. All open
questions in §14 of the research file are resolved here.

## 1. Charter (locked)

Replace the three TM-D2-keyed 501 stubs with real handlers backed by
Postgres:

| Method | Path | Source table |
|---|---|---|
| GET | `/api/v1/status/live` | `raw.line_status` (live, <30 s) |
| GET | `/api/v1/status/history` | `stg_line_status` (typed, dbt-lagged) |
| GET | `/api/v1/reliability/{line_id}` | `mart_tube_reliability_daily` |

**One PR** for all three (research §14 Q1). No split. Estimated
diff ≈ 350–450 LoC of source + tests, well under the 600-LoC threshold.

## 2. Decisions (Phase 2 lock)

| # | Question | Decision |
|---|---|---|
| 1 | Scope | Single PR, three endpoints. |
| 2 | `/status/live` source | `raw.line_status` + JSONB casts, 15-min `ingested_at` window. |
| 3 | `/status/history` safety | Hard cap `to - from <= 30d` (HTTP 400 otherwise) **and** `LIMIT 10000`. |
| 4 | Pool dep | Add `psycopg[binary,pool]` extra to existing `psycopg` line in `pyproject.toml`. |
| 5 | `DATABASE_URL` | Optional. Lifespan no-ops when unset. Handlers needing DB return **503 Service Unavailable** with RFC 7807 body. |
| 6 | Pool size | Hard-code `min_size=1, max_size=4`, no env knob. |
| 7 | `reliability_percent` rounding | 1 decimal place (`round(value, 1)`). |
| 8 | `severity_histogram` keys | `dict[str, int]`, only severities with ≥ 1 snapshot in window. |
| 9 | `severity_histogram` density | No zero-count entries. |
| 10 | Reliability empty result | HTTP **404** with RFC 7807, detail: `"No reliability data for line {line_id} in the last {window} days"`. |
| 11 | Reliability query param | OpenAPI says `window`. Pydantic model field on response is `window_days`. Echo the request `window` value into `window_days` in the response. |
| 12 | Pydantic models location | New `src/api/schemas.py`. Names: `LineStatusResponse`, `LineReliabilityResponse`, `Problem`. |
| 13 | Handler module layout | Flat. Keep all handlers in `src/api/main.py`; SQL helpers in `src/api/db.py`. No `src/api/routes/` directory. |
| 14 | Integration tests | Bypass dbt — seed `raw.line_status` and `mart_tube_reliability_daily` directly. dbt → mart contract is covered by TM-C2 dbt tests. |
| 15 | 404 / 400 / 503 envelope | RFC 7807 problem object built by a small `problem(...)` helper in `src/api/main.py` (or `src/api/errors.py`). |
| 16 | `/health` | Untouched. `dependencies` stays `{}`. No DB ping (revisit in TM-D5/TM-A5). |

## 3. Acceptance criteria (locked)

Functional:

- [ ] `GET /api/v1/status/live` → `200 LineStatus[]`, latest snapshot
      per `line_id` from `raw.line_status` constrained to
      `ingested_at >= now() - INTERVAL '15 minutes'`, ordered by
      `line_id` ASC.
- [ ] `GET /api/v1/status/history?from=…&to=…[&line_id=…]`:
  - `from`, `to` required, RFC 3339, parsed as timezone-aware
    `datetime` (UTC).
  - `from >= to` → **400** problem.
  - `to - from > 30 days` → **400** problem.
  - Returns rows from `stg_line_status` where
    `valid_from >= from AND valid_from < to`, `LIMIT 10000`,
    ordered by `valid_from ASC, line_id ASC`.
- [ ] `GET /api/v1/reliability/{line_id}?window=N`:
  - `window` defaults to 7, 1 ≤ N ≤ 90 (FastAPI `Query` validator).
    Out-of-range → **422** (FastAPI default for path/query
    validation, RFC 7807 envelope wrapping is *not* required for
    this case — matches existing FastAPI default behaviour).
  - Single grouped query against `mart_tube_reliability_daily`
    filtered by `line_id` and `calendar_date >= current_date - window`.
  - Empty result → **404** problem.
  - `reliability_percent` = `100 * SUM(snapshot_count FILTER status_severity = 10) / SUM(snapshot_count)`, rounded to 1 decimal.
  - `severity_histogram` is `dict[str, int]` of present severities only.

Non-functional:

- [ ] All SQL parameterised. No f-string SQL. No string interpolation
      of caller input.
- [ ] `pyproject.toml` updated to `psycopg[binary,pool]>=3.2`.
      `uv.lock` regenerated.
- [ ] FastAPI lifespan creates one `AsyncConnectionPool` per process,
      `min_size=1, max_size=4`, attached to `app.state.db_pool`.
      Pool is closed on shutdown.
- [ ] Lifespan is **no-op** when `DATABASE_URL` env var is missing
      (matches Logfire's `if-token-present` pattern). Handlers raise
      503 problem when called without a pool. `/health` keeps working.
- [ ] CORS allowlist unchanged (`http://localhost:3000`,
      `https://tfl-monitor.vercel.app`), `allow_credentials=True`.
- [ ] OpenAPI bidirectional drift checks in `tests/api/test_stubs.py`
      stay green.
- [ ] `tests/api/test_stubs.py` STUB_ROUTES no longer lists the three
      TM-D2 routes.
- [ ] New unit tests in `tests/api/test_status_live.py`,
      `test_status_history.py`, `test_reliability.py` cover happy
      path + every error branch.
- [ ] New integration tests in `tests/integration/test_status_live.py`,
      `test_status_history.py`, `test_reliability.py`, gated on
      `DATABASE_URL`, mirroring `tests/integration/test_sql_init.py`.
- [ ] `tests/test_health.py` still passes without `DATABASE_URL`.
- [ ] `uv run task lint` (ruff + ruff format + mypy strict) green.
- [ ] `uv run task test` (default, hermetic) green.
- [ ] `uv run bandit -r src --severity-level high` reports no findings.
- [ ] `make check` green end-to-end.
- [ ] `PROGRESS.md` row flipped to ✅ with completion date.
- [ ] PR title `feat(api): TM-D2 wire status + reliability to Postgres`,
      body closes the matching Linear issue.

## 4. What we are NOT doing

Out of scope for this WP — pushed to other WPs or the backlog:

- `/api/v1/disruptions/recent` and `/api/v1/bus/{stop_id}/punctuality`
  → **TM-D3**. They stay 501.
- `/api/v1/chat/*` endpoints → **TM-D5**. They stay 501.
- Postgres ping inside `/health` `dependencies` → revisit in TM-D5/TM-A5.
- `ref.lines` lookups (line metadata enrichment). Code reads
  `line_name` and `mode` directly from the snapshot/mart columns. No
  JOIN against `ref.lines`. (Consequence: if a line snapshot ever
  lacked `line_name` or `mode`, the row would still surface — not a
  real concern, the producer normaliser fills both.)
- A `get_pool` FastAPI dependency injection helper. Handlers read
  `request.app.state.db_pool` directly (lean — adding `Depends(...)`
  would not buy us testability we cannot already get by patching
  `app.state.db_pool`).
- Splitting handlers into `src/api/routes/`. One ~120-line `main.py`
  is fine.
- Materialised view for live status. Direct query against
  `raw.line_status` is fast enough at the data sizes we expect.
- Env-tunable pool size. Hard-coded for now.
- New ADR. None of the decisions above contradicts an existing ADR
  or makes an irreversible architectural choice; the
  `psycopg[binary,pool]` extra is reversible. If Phase 3 surfaces a
  surprise, capture it as an ADR then.
- Frontend wiring (`/status/live` consumed by the dashboard). That is
  **TM-E1b** — already queued.
- Linear MCP work to file the issue. The PR body will reference the
  Linear ID once Codex/the author confirm it (default placeholder
  `TM-XX` until then).

## 5. Implementation phases (Phase 3)

Five internal phases. Each phase ends with `uv run task lint && uv run task test` clean before proceeding. If any phase diverges from the plan, stop and report rather than improvising.

### Phase 3.1 — dependency and pool plumbing

- `pyproject.toml`: bump `psycopg[binary]>=3.2` → `psycopg[binary,pool]>=3.2`.
- `uv lock --upgrade-package psycopg-pool` (or just `uv lock`) so the
  lockfile resolves `psycopg-pool`.
- `src/api/db.py` (new):
  - Module docstring.
  - `def build_pool(dsn: str) -> AsyncConnectionPool` — thin factory
    with `min_size=1, max_size=4, open=False`. Type-only; opening is
    awaited by the lifespan.
  - SQL constants and query helpers (added incrementally in 3.2–3.4).
- `src/api/main.py`:
  - Add `lifespan` async context manager. Read
    `DATABASE_URL`. If unset, set `app.state.db_pool = None` and
    yield. If set, build the pool, `await pool.open()`, attach to
    `app.state.db_pool`, yield, then `await pool.close()`.
  - Pass `lifespan=lifespan` into `FastAPI(...)`.
- `src/api/main.py`: small `_problem(status: int, title: str,
  detail: str) -> JSONResponse` helper that emits
  `application/problem+json`. Used by 400/404/503 paths.
- Type hints: `psycopg-pool` ships `py.typed` since 3.2 — verify
  `mypy --strict` is happy. If a stub is missing, add a tight
  `[[tool.mypy.overrides]] module = ["psycopg_pool", "psycopg_pool.*"]`
  block (preferred over `Any`-blanketing).

**Phase exit:** `tests/test_health.py` still green without
`DATABASE_URL`. `test_stubs.py` still green (no behaviour change yet).

### Phase 3.2 — `/status/live`

- `src/api/schemas.py` (new):
  - `Mode = Literal[...]` matching the OpenAPI enum.
  - `class LineStatusResponse(BaseModel)` with `model_config =
    ConfigDict(extra="forbid")` and the eight fields from §3 of the
    research file.
- `src/api/db.py`:
  - `LIVE_STATUS_SQL` — the parameterised `DISTINCT ON` query from
    research §7 (Option A) with the 15-minute `ingested_at` window.
  - `async def fetch_live_status(pool) -> list[LineStatusResponse]`.
- `src/api/main.py`:
  - Replace the `_not_implemented` body of `get_status_live` with a
    call to `fetch_live_status`. Return `list[LineStatusResponse]`,
    set `response_model=list[LineStatusResponse]`. Drop
    `response_model=None`. 503 problem when pool missing.
- `tests/api/test_status_live.py` (new):
  - Fake pool fixture (`tests/conftest.py`, see §6).
  - Happy path returns rows in `line_id` order with proper Pydantic
    coercion (string → datetime).
  - Empty result → `200 []`.
  - Missing pool → `503 problem+json`.
- `tests/api/test_stubs.py`: drop the live row from `STUB_ROUTES`.
- `tests/integration/test_status_live.py` (new):
  - `pytest.importorskip("psycopg")`,
    `pytest.mark.skipif(not os.getenv("DATABASE_URL"), ...)`.
  - Insert two events into `raw.line_status` (one stale, one fresh)
    via sync `psycopg.connect`; hit `/status/live` with
    `TestClient(app)`; assert only the fresh one comes back.

### Phase 3.3 — `/status/history`

- `src/api/main.py`:
  - Type the handler signature as
    `async def get_status_history(request: Request, from_: datetime
    = Query(..., alias="from"), to: datetime = Query(...), line_id:
    str | None = Query(None)) -> list[LineStatusResponse]`.
  - Validate `from < to` and `to - from <= timedelta(days=30)`,
    return 400 problem otherwise.
  - 503 if no pool.
- `src/api/db.py`:
  - `HISTORY_SQL` against `analytics.stg_line_status` (or whatever
    schema dbt emits — verify in Phase 3.0 by reading
    `dbt/profiles.yml` or `dbt run` target schema; default schema
    is `public`/`analytics`). Use parameter placeholders `%(from)s`,
    `%(to)s`, `%(line_id)s`. `LIMIT 10000`. Order
    `valid_from ASC, line_id ASC`.
  - `async def fetch_status_history(pool, *, from_dt, to_dt, line_id)
    -> list[LineStatusResponse]`.
- `tests/api/test_status_history.py` (new): unit cases for happy
  path, `from > to` (400), 31-day window (400), `line_id` filter
  passes through to SQL params (assert via fake pool's recorded SQL),
  503 when no pool.
- `tests/integration/test_status_history.py` (new): seed
  `stg_line_status` directly via `INSERT … VALUES`, exercise the
  endpoint, assert ordering + `line_id` filter + window bounds.

### Phase 3.4 — `/reliability/{line_id}`

- `src/api/schemas.py`:
  - `class LineReliabilityResponse(BaseModel)` with
    `extra="forbid"`. Fields: `line_id`, `line_name`, `mode`,
    `window_days: int`, `reliability_percent: float`,
    `sample_size: int`, `severity_histogram: dict[str, int]`.
- `src/api/db.py`:
  - `RELIABILITY_AGG_SQL` and `RELIABILITY_HISTOGRAM_SQL` against
    `mart_tube_reliability_daily`.
  - `async def fetch_reliability(pool, *, line_id, window) ->
    LineReliabilityResponse | None`. Return `None` when
    `sample_size == 0`.
  - Single connection checkout, two `cursor.execute` calls (ok —
    histogram is small).
- `src/api/main.py`:
  - Replace `get_line_reliability` body. Use FastAPI `Query` with
    `ge=1, le=90` for `window`. 404 problem when result is `None`.
    503 when no pool.
- `tests/api/test_reliability.py` (new): happy path,
  empty → 404, `window` clamping returns 422 from FastAPI for
  `window=0` and `window=91`, 503 when no pool, histogram excludes
  zero-count keys (via fake pool returning a histogram with one
  severity).
- `tests/integration/test_reliability.py` (new): seed
  `mart_tube_reliability_daily` directly, exercise endpoint, assert
  `reliability_percent` rounding and histogram correctness.

### Phase 3.5 — wiring up

- `tests/conftest.py` (root, new):
  - `FakeAsyncPool` and `FakeAsyncConnection` (recorded SQL +
    canned rows). One file, exposed as `pytest` fixtures
    `fake_pool` / `fake_pool_factory`.
  - Fixture that monkeypatches `app.state.db_pool` for the duration
    of a test, with proper teardown.
- `PROGRESS.md`: flip the row to ✅ with completion date.
- Verify `make check` clean; squash where appropriate; produce the
  PR description (PT-BR allowed in body, English on subject).

## 6. Test fixtures — `tests/conftest.py`

The unit test fakes are the most error-prone piece. Spec the
contract here so Phase 3 doesn't drift:

```python
class FakeAsyncCursor:
    def __init__(self, rows: list[tuple]) -> None: ...
    async def __aenter__(self) -> "FakeAsyncCursor": ...
    async def __aexit__(self, *a) -> None: ...
    async def execute(self, sql: str, params: dict | None = None) -> None:
        # records (sql, params) on the parent connection
        ...
    async def fetchall(self) -> list[tuple]: ...
    async def fetchone(self) -> tuple | None: ...

class FakeAsyncConnection:
    executed: list[tuple[str, dict | None]]
    def __init__(self, batches: list[list[tuple]]) -> None: ...
    def cursor(self, *, row_factory=None) -> FakeAsyncCursor: ...

class FakeAsyncPool:
    def __init__(self, conn: FakeAsyncConnection) -> None: ...
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[FakeAsyncConnection]: ...
    async def open(self) -> None: ...  # no-op
    async def close(self) -> None: ...  # no-op
```

`row_factory` parameter is a deliberate stub: psycopg supports it
but our fakes ignore it and return whatever `batches` were primed —
we shape rows in fixtures to match the column order of the real
SQL. Tests assert on the recorded `(sql, params)` plus the resulting
JSON, which is what matters.

## 7. SQL — locked drafts

These are the queries Phase 3 should implement (no string
interpolation; bind via psycopg `%(name)s` named params). Final
schema-qualified table names (`analytics.stg_line_status`,
`analytics.mart_tube_reliability_daily`) confirmed in Phase 3.0 by
reading `dbt/profiles.yml`; if dbt emits to `public`, the
`analytics.` prefix is dropped.

### `/status/live`

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
  AND ingested_at >= now() - INTERVAL '15 minutes'
ORDER BY payload->>'line_id', ingested_at DESC;
```

### `/status/history`

```sql
SELECT line_id, line_name, mode,
       status_severity, status_severity_description,
       reason, valid_from, valid_to
FROM stg_line_status
WHERE valid_from >= %(from)s
  AND valid_from <  %(to)s
  AND ( %(line_id)s IS NULL OR line_id = %(line_id)s )
ORDER BY valid_from ASC, line_id ASC
LIMIT 10000;
```

### `/reliability/{line_id}` aggregate

```sql
SELECT
    line_id,
    MIN(line_name) AS line_name,
    MIN(mode)      AS mode,
    SUM(snapshot_count)::int AS sample_size,
    CASE WHEN SUM(snapshot_count) = 0 THEN 0
         ELSE ROUND(
             100.0
             * SUM(snapshot_count) FILTER (WHERE status_severity = 10)
             / SUM(snapshot_count),
             1
         )::float
    END AS reliability_percent
FROM mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - %(window)s::int)
GROUP BY line_id;
```

### `/reliability/{line_id}` histogram

```sql
SELECT status_severity::text AS severity,
       SUM(snapshot_count)::int AS count
FROM mart_tube_reliability_daily
WHERE line_id = %(line_id)s
  AND calendar_date >= (current_date - %(window)s::int)
GROUP BY status_severity
ORDER BY status_severity;
```

## 8. Files expected to change

New:

- `src/api/schemas.py`
- `src/api/db.py`
- `tests/conftest.py`
- `tests/api/test_status_live.py`
- `tests/api/test_status_history.py`
- `tests/api/test_reliability.py`
- `tests/integration/test_status_live.py`
- `tests/integration/test_status_history.py`
- `tests/integration/test_reliability.py`

Modified:

- `pyproject.toml` (extra `pool`)
- `uv.lock` (regenerated)
- `src/api/main.py` (lifespan, three handlers, problem helper,
  imports, `response_model` set)
- `tests/api/test_stubs.py` (drop three rows from `STUB_ROUTES`)
- `PROGRESS.md` (TM-D2 row → ✅)

Untouched:

- `contracts/openapi.yaml` (frozen).
- `contracts/schemas/*` (Kafka tier).
- `dbt/` (mart already in `main`).
- `src/api/observability.py` (Logfire + psycopg already wired).
- `web/` (TM-E1b is the next WP).
- `Makefile`, `docker-compose.yml`.

## 9. Risks revisited

Carried from research §13, with mitigation locked:

| Risk | Mitigation |
|---|---|
| Lifespan break of `tests/test_health.py`. | Pool is optional — lifespan no-ops without `DATABASE_URL` (decision §2.5). Smoke test stays green. |
| `test_stubs.py` parametrised lock fails. | Drop the three TM-D2 rows from `STUB_ROUTES` in the same PR. The bidirectional drift checks must still pass. |
| `mart_tube_reliability_daily` empty without dbt run. | Integration tests insert into the mart directly (decision §2.14). dbt → mart contract is covered by TM-C2 dbt tests. |
| `mode` filtering on reliability endpoint. | Endpoint is keyed by `line_id`, so mode is informational only. No filter needed. |
| `mypy strict` against `psycopg_pool`. | `psycopg-pool 3.2+` ships `py.typed`. Verify in Phase 3.1; add a `[[tool.mypy.overrides]]` block only if `mypy --strict` complains. |
| Bandit on DSN handling. | Pool reads `os.environ["DATABASE_URL"]` once. DSN is never logged or echoed. |
| psycopg async connection serialisation. | The pool gives one connection per request; we never share a connection across awaits. |

## 10. Confirmation gate

Before starting Phase 3:

1. Read `.claude/specs/TM-D2-research.md` and this plan side-by-side.
2. Confirm the dbt target schema for `stg_line_status` /
   `mart_tube_reliability_daily` (read `dbt/profiles.yml` and any
   project-level `+schema:` config). Patch §7 SQL if the schema is
   not bare.
3. Confirm `uv` resolves `psycopg-pool` cleanly on the local
   platform (run `uv lock --upgrade-package psycopg` in a scratch
   branch first).

If any of the above surfaces a surprise, stop and report:
> *Expected: X. Found: Y. How should I proceed?*
