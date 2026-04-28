# TM-D3 — Plan (Phase 2)

Implementation plan for **TM-D3: Remaining endpoints (disruptions,
bus)**. Built from `.claude/specs/TM-D3-research.md`. All open
questions in §13 of the research file are resolved here.

## 1. Charter (locked)

Replace the two TM-D3-keyed 501 stubs with real handlers:

| Method | Path | Source table |
|---|---|---|
| GET | `/api/v1/disruptions/recent` | `analytics.stg_disruptions` (snapshot grain), with optional `EXISTS` subquery against `analytics.stg_line_status` for the `mode` filter |
| GET | `/api/v1/bus/{stop_id}/punctuality` | `analytics.stg_arrivals` (raw predictions); on-time/early/late buckets composed via `FILTER` clauses on `time_to_station_seconds` |

**One PR** for both endpoints. Estimated diff ≈ 250–350 LoC of
source + tests, well under the 600-LoC threshold.

## 2. Decisions (Phase 2 lock)

| # | Question | Decision |
|---|---|---|
| 1 | Recency window | None. `LIMIT %(limit)s` + `ORDER BY last_update DESC NULLS LAST, ingested_at DESC` only. |
| 2 | `mode` filter | `EXISTS (SELECT 1 FROM analytics.stg_line_status sls WHERE sls.mode = %(mode)s AND sls.line_id IN (SELECT jsonb_array_elements_text(...)))`. |
| 3 | Disruption source | `analytics.stg_disruptions`. Mart drops snapshot fields the contract requires. |
| 4 | Bus source | `analytics.stg_arrivals`. The mart filters by empty `ref.lines` and lacks `station_name`. |
| 5 | Bucket boundaries | `late = ttsr < 0`, `on_time = ttsr BETWEEN 0 AND 300`, `early = ttsr > 300`. Anchored to TfL's published 5-minute bus performance KPI. Documented as a proxy in SQL + handler docstring. |
| 6 | `stop_name` source | Second query against `analytics.stg_arrivals`, `ORDER BY ingested_at DESC LIMIT 1`. Two queries, one connection — mirrors TM-D2 `/reliability`. |
| 7 | `window_days` | Hard-coded **7**. Matches the OpenAPI example. No new query parameter. |
| 8 | Bus 404 path | When the punctuality query returns `sample_size = 0` **or** the `stop_name` query returns no row, the fetcher returns `None` and the handler emits `404 application/problem+json` with detail `"No punctuality data for stop {stop_id}"`. |
| 9 | Pool missing | 503 problem (reuses `_problem` from TM-D2). |
| 10 | Pydantic models | `DisruptionResponse`, `BusPunctualityResponse` in `src/api/schemas.py`, `extra="forbid"`, OpenAPI shapes mirrored exactly. |
| 11 | Handler layout | Flat in `src/api/main.py`. No `src/api/routes/` directory (D2 plan §4 forbids it). |
| 12 | Pool DI | Handlers read `request.app.state.db_pool` directly. No `Depends(get_pool)` (D2 plan §4 forbids it). |
| 13 | Integration tests | Bypass dbt — seed `analytics.stg_disruptions` and `analytics.stg_arrivals` directly via sync `psycopg.connect`, mirroring TM-D2 `test_status_history.py` / `test_reliability.py`. |
| 14 | Schema-qualification | Every staging/mart reference qualified with `analytics.` (matches `dbt/profiles.yml`). |

## 3. Acceptance criteria (locked)

Functional:

- [ ] `GET /api/v1/disruptions/recent[?limit=N&mode=...]`:
  - `limit` defaults to 50, validated `1 ≤ limit ≤ 200`. Out of
    range yields 422 (FastAPI default).
  - `mode` is optional `Literal[...]`; out-of-enum yields 422.
  - Returns `Disruption[]` ordered by
    `last_update DESC NULLS LAST, ingested_at DESC`.
  - Sourced from `analytics.stg_disruptions`. `mode` filter applied
    via `EXISTS` against `analytics.stg_line_status`.
  - `closure_text` always non-null in the response (`COALESCE` at SQL).
  - Pool missing → 503 RFC 7807.
- [ ] `GET /api/v1/bus/{stop_id}/punctuality`:
  - No query parameters. `window_days` is hard-coded to 7 in both
    SQL and response.
  - Returns `BusPunctuality` with on-time/early/late percents
    derived as a proxy from `time_to_station_seconds` over the last
    7 days (`ingested_at >= now() - 7 days`).
  - Returns 404 RFC 7807 with detail
    `"No punctuality data for stop {stop_id}"` when no arrivals were
    ingested for that stop in the window (or when no `stop_name` is
    available).
  - Pool missing → 503 RFC 7807.

Non-functional:

- [ ] All SQL parameterised, named `%(name)s` placeholders. No
      f-strings around user input. No string interpolation.
- [ ] Schema-qualified table names everywhere
      (`analytics.stg_disruptions`, `analytics.stg_arrivals`,
      `analytics.stg_line_status`).
- [ ] CORS allowlist unchanged.
- [ ] OpenAPI bidirectional drift checks in
      `tests/api/test_stubs.py` stay green.
- [ ] `tests/api/test_stubs.py::STUB_ROUTES` no longer lists the two
      TM-D3 routes.
- [ ] New unit tests in `tests/api/test_disruptions_recent.py` and
      `tests/api/test_bus_punctuality.py` cover happy, empty, 503,
      422 / Literal validator, and (bus only) 404.
- [ ] New integration tests in
      `tests/integration/test_disruptions_recent.py` and
      `tests/integration/test_bus_punctuality.py`, gated on
      `DATABASE_URL`, mirroring TM-D2 `test_status_history.py`.
- [ ] `tests/test_health.py`, `tests/api/test_status_*`,
      `tests/api/test_reliability.py`, `tests/api/test_stubs.py` all
      keep passing.
- [ ] `uv run task lint` (ruff + ruff format + mypy strict) green.
- [ ] `uv run task test` (default, hermetic) green.
- [ ] `uv run bandit -r src --severity-level high` reports no findings.
- [ ] `make check` green end-to-end.
- [ ] `PROGRESS.md` TM-D3 row flipped to ✅ 2026-04-28 with a paragraph
      note matching the verbosity of D2's note.
- [ ] PR title `feat(api): TM-D3 wire disruptions + bus punctuality`,
      body closes Linear `TM-14`.

## 4. What we are NOT doing

Out of scope for this WP — pushed to other WPs or the backlog:

- `/api/v1/chat/*` endpoints → **TM-D5**. They stay 501.
- `/health` Postgres ping → **TM-D5/TM-A5**. `dependencies` payload
  stays `{}`.
- Frontend wiring (Disruption Log view) → **TM-E2**.
- `ref.lines` population → **TM-A2/TM-A3**. The `mode` filter for
  disruptions degrades gracefully when `stg_line_status` is empty
  (no rows match), which is the same behaviour as the rest of the
  API today.
- Adding a `mart_bus_metrics_daily` rewrite that includes
  `station_name` or punctuality buckets — that touches `dbt/`
  (C-dbt track). Surfaced in the final report, not fixed here.
- Adding a `window` query parameter to the bus endpoint. The
  contract does not declare one; we hard-code 7 days.
- Splitting handlers into `src/api/routes/`. D2 plan §4 forbids it.
- Adding a `get_pool` FastAPI dependency. D2 plan §4 forbids it.
- Custom metrics or tracing. LangSmith + Logfire are the only
  observability (CLAUDE.md §"Anti-patterns to avoid").
- A new ADR. The bus punctuality proxy is documented in the SQL
  comment, the handler docstring, and the PR body — that is enough
  documentation for a portfolio. If the proxy is renegotiated in a
  future review, capture it as an ADR then.

## 5. Implementation phases (Phase 3)

Three internal phases. Each ends with `uv run task lint && uv run
task test` clean before proceeding. If any phase diverges from the
plan, stop and report rather than improvise.

### Phase 3.1 — Schemas + SQL constants + fetchers

- `src/api/schemas.py`:
  - Add `DisruptionCategory = Literal["RealTime", "PlannedWork",
    "Information", "Incident", "Undefined"]`.
  - Add `class DisruptionResponse(BaseModel)` with
    `model_config = ConfigDict(extra="forbid")` and the eleven
    fields from the OpenAPI `Disruption` schema. `category: DisruptionCategory`,
    `affected_routes: list[str]`, `affected_stops: list[str]`,
    `severity: int = Field(ge=0)`, `created` and `last_update` as
    `datetime`.
  - Add `class BusPunctualityResponse(BaseModel)` with
    `extra="forbid"` and the seven fields from `BusPunctuality`:
    `stop_id: str`, `stop_name: str`,
    `window_days: int = Field(ge=1, le=90)`,
    `on_time_percent: float = Field(ge=0.0, le=100.0)`,
    `early_percent: float = Field(ge=0.0, le=100.0)`,
    `late_percent: float = Field(ge=0.0, le=100.0)`,
    `sample_size: int = Field(ge=0)`.
- `src/api/db.py`:
  - Add `Mode` import (or duplicate the literal — lean: import from
    `api.schemas`).
  - Add `DISRUPTIONS_SQL` constant. Inline comment explains the
    `EXISTS` subquery trick for the `mode` filter and the
    `last_update DESC NULLS LAST, ingested_at DESC` ordering choice.
  - Add `BUS_PUNCTUALITY_SQL` constant. Inline comment explains the
    proxy bucket boundaries (0/300 s = TfL 5-minute KPI threshold)
    and that this is a proxy, not a ground-truth KPI.
  - Add `BUS_STOP_NAME_SQL` constant.
  - Add `async def fetch_recent_disruptions(pool, *, limit, mode)
    -> list[DisruptionResponse]`.
  - Add `async def fetch_bus_punctuality(pool, *, stop_id, window)
    -> BusPunctualityResponse | None`. Returns `None` when
    `sample_size == 0` or `stop_name` is missing.

### Phase 3.2 — Handlers in `src/api/main.py`

- Replace the body of `get_recent_disruptions`:
  ```python
  @app.get(
      "/api/v1/disruptions/recent",
      operation_id="get_recent_disruptions",
      response_model=list[DisruptionResponse],
  )
  async def get_recent_disruptions(
      request: Request,
      limit: Annotated[int, Query(ge=1, le=200)] = 50,
      mode: Annotated[Mode | None, Query()] = None,
  ) -> list[DisruptionResponse] | Response:
      pool = request.app.state.db_pool
      if pool is None:
          return _problem(503, "Service Unavailable", "Database pool is not available")
      return await fetch_recent_disruptions(pool, limit=limit, mode=mode)
  ```
- Replace the body of `get_bus_punctuality`:
  ```python
  @app.get(
      "/api/v1/bus/{stop_id}/punctuality",
      operation_id="get_bus_punctuality",
      response_model=BusPunctualityResponse,
  )
  async def get_bus_punctuality(
      request: Request,
      stop_id: str,
  ) -> BusPunctualityResponse | Response:
      pool = request.app.state.db_pool
      if pool is None:
          return _problem(503, "Service Unavailable", "Database pool is not available")
      result = await fetch_bus_punctuality(pool, stop_id=stop_id, window=7)
      if result is None:
          return _problem(
              404,
              "Not Found",
              f"No punctuality data for stop {stop_id}",
          )
      return result
  ```
- Update imports: bring in `DisruptionResponse`,
  `BusPunctualityResponse`, `Mode`, `fetch_recent_disruptions`,
  `fetch_bus_punctuality`.
- Drop unused `_not_implemented` if both 501 paths go away — but
  `/chat/*` still uses it, so keep it.

### Phase 3.3 — Tests + STUB_ROUTES delta + PROGRESS update

- `tests/api/test_stubs.py`: drop the two TM-D3 rows from
  `STUB_ROUTES`. Bidirectional drift checks must keep passing.
- `tests/api/test_disruptions_recent.py` (new): unit cases per §6
  below.
- `tests/api/test_bus_punctuality.py` (new): unit cases per §6
  below.
- `tests/integration/test_disruptions_recent.py` (new): seed
  `analytics.stg_disruptions` directly via sync `psycopg.connect`;
  exercise endpoint; assert ordering + `closure_text` non-null.
- `tests/integration/test_bus_punctuality.py` (new): seed
  `analytics.stg_arrivals` directly; exercise happy path and
  unknown-stop 404.
- `PROGRESS.md`: flip TM-D3 row to ✅ 2026-04-28 with a verbose note
  matching the D2 row.

## 6. Test fixtures and cases

All unit tests reuse `tests/conftest.py::FakeAsyncPool`,
`fake_pool_factory`, `attach_pool`. No new fixtures needed.

### `tests/api/test_disruptions_recent.py`

| Case | Setup | Assertion |
|---|---|---|
| `test_happy_path_default_limit` | `fake_pool_factory` returns a list of two disruption rows | `200`; body has 2 items; sql == `DISRUPTIONS_SQL`; params `{"limit": 50, "mode": None}` |
| `test_returns_empty_list_when_no_rows` | empty batch | `200 []` |
| `test_mode_filter_passes_through` | mock returns `[]`; call with `?mode=tube` | sql params `mode == "tube"` |
| `test_invalid_mode_returns_422` | call with `?mode=spaceship` | `422` (FastAPI default for `Literal`) |
| `test_limit_below_min_returns_422` | call with `?limit=0` | `422` |
| `test_limit_above_max_returns_422` | call with `?limit=201` | `422` |
| `test_closure_text_null_becomes_empty_string` | row has `closure_text = ""` (already coalesced by SQL) | response `closure_text == ""` |
| `test_missing_pool_returns_503` | `attach_pool(None)` | `503 application/problem+json` |

### `tests/api/test_bus_punctuality.py`

| Case | Setup | Assertion |
|---|---|---|
| `test_happy_path_buckets` | first batch: `[{"sample_size": 100, "late_count": 10, "on_time_count": 80, "early_count": 10}]`; second batch: `[{"station_name": "Trafalgar Square"}]` | response matches OpenAPI example shape (percents = 80.0/10.0/10.0); `window_days == 7`; sql == `BUS_PUNCTUALITY_SQL` then `BUS_STOP_NAME_SQL`; params `{"stop_id": "490008660N", "window": 7}` then `{"stop_id": "490008660N"}` |
| `test_zero_sample_returns_404` | first batch: `[{"sample_size": 0, "late_count": 0, "on_time_count": 0, "early_count": 0}]` | `404 application/problem+json`; detail mentions stop_id |
| `test_missing_station_name_returns_404` | first batch: non-zero counts; second batch: `[]` | `404` |
| `test_aggregate_returns_no_row_returns_404` | first batch: `[]` | `404` |
| `test_missing_pool_returns_503` | `attach_pool(None)` | `503` |

### Integration tests

`tests/integration/test_disruptions_recent.py`:
- Marker `pytest.mark.integration`, skipif `DATABASE_URL` unset.
- `_ensure_table(cur)` creates `analytics.stg_disruptions` if dbt
  has not built it yet (mirrors TM-D2 pattern).
- Insert two rows with different `last_update` timestamps.
- Hit the endpoint; assert ordering and `closure_text` non-null.
- Cleanup fixture deletes test rows on entry and exit.

`tests/integration/test_bus_punctuality.py`:
- Marker + skipif identical.
- `_ensure_table(cur)` creates `analytics.stg_arrivals` if missing.
- Insert four arrival rows for the same `station_id` with varying
  `time_to_station_seconds` to populate all three buckets.
- Hit the endpoint; assert percents add to ~100.0 within tolerance,
  `stop_name` echoed, `sample_size` == 4.
- Second test: hit endpoint with an unknown `stop_id`; assert 404.
- Cleanup fixture mirrors the disruption one.

## 7. SQL — locked

### `/disruptions/recent`

```sql
SELECT
    disruption_id,
    category,
    category_description,
    description,
    summary,
    COALESCE(closure_text, '')                            AS closure_text,
    severity,
    created,
    last_update,
    affected_routes,
    affected_stops
FROM analytics.stg_disruptions sd
WHERE event_type = 'disruptions.snapshot'
  AND (
      %(mode)s IS NULL
      OR EXISTS (
          SELECT 1
          FROM analytics.stg_line_status sls
          WHERE sls.mode = %(mode)s
            AND sls.line_id IN (
                SELECT jsonb_array_elements_text(sd.affected_routes)
            )
      )
  )
ORDER BY last_update DESC NULLS LAST, ingested_at DESC
LIMIT %(limit)s
```

Two psycopg-bound parameters: `%(mode)s` (string or NULL) and
`%(limit)s` (int 1–200). The triple-keyed `%(mode)s` (in the OR
short-circuit and again in the EXISTS subquery) shows up as a single
binding in psycopg's named-parameter substitution — psycopg expands
the same named parameter at every site.

### `/bus/{stop_id}/punctuality` — punctuality buckets

```sql
SELECT
    COUNT(*)::int AS sample_size,
    COUNT(*) FILTER (WHERE time_to_station_seconds < 0)::int AS late_count,
    COUNT(*) FILTER (
        WHERE time_to_station_seconds BETWEEN 0 AND 300
    )::int AS on_time_count,
    COUNT(*) FILTER (WHERE time_to_station_seconds > 300)::int AS early_count
FROM analytics.stg_arrivals
WHERE station_id = %(stop_id)s
  AND ingested_at >= now() - (%(window)s::int * INTERVAL '1 day')
```

### `/bus/{stop_id}/punctuality` — stop name

```sql
SELECT station_name
FROM analytics.stg_arrivals
WHERE station_id = %(stop_id)s
ORDER BY ingested_at DESC
LIMIT 1
```

## 8. Files expected to change

New:

- `tests/api/test_disruptions_recent.py`
- `tests/api/test_bus_punctuality.py`
- `tests/integration/test_disruptions_recent.py`
- `tests/integration/test_bus_punctuality.py`

Modified:

- `src/api/db.py` — add `DISRUPTIONS_SQL`, `BUS_PUNCTUALITY_SQL`,
  `BUS_STOP_NAME_SQL` constants and two async fetchers.
- `src/api/schemas.py` — add `DisruptionCategory`,
  `DisruptionResponse`, `BusPunctualityResponse`.
- `src/api/main.py` — replace 501 stub bodies; new imports.
- `tests/api/test_stubs.py` — drop two TM-D3 rows from
  `STUB_ROUTES`.
- `PROGRESS.md` — flip TM-D3 row to ✅ 2026-04-28.

Untouched:

- `contracts/openapi.yaml` (frozen).
- `contracts/schemas/*` (Kafka tier).
- `dbt/` (mart layer; TM-C3 already in main).
- `web/` (TM-E2 owns disruption log view).
- `src/ingestion/` (B-ingestion track).
- `airflow/` (A-infra track).
- `Makefile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`.

## 9. Risks revisited

Carried from research §12, mitigations locked:

| Risk | Mitigation |
|---|---|
| Bus punctuality is a proxy, not ground truth. | Document in SQL inline comment, handler docstring, and PR body. The phrase "proxy on top of `time_to_station_seconds`" appears in all three places. |
| `stg_disruptions` empty until TM-B4 + dbt run. | Integration tests seed staging directly, mirroring TM-D2. |
| `stg_line_status` empty in some test DBs. | Unit tests cover the `mode=...` path with the fake pool. The integration test for disruptions exercises only `mode IS NULL`. |
| `closure_text` nullability mismatch. | SQL `COALESCE(closure_text, '')` resolves it server-side. |
| JSONB → Python list serialisation. | psycopg with `dict_row` returns lists; verified by unit tests asserting on response shape. |
| Bucket boundary push-back. | TfL 5-minute KPI anchors the choice. SQL comment cites the rationale. |
| NaPTAN scope. | Endpoint trusts caller's `stop_id`. Tube ids return zero arrivals → 404. Documented as acceptable in the PR body. |
| Bandit on SQL constants. | Strings, parameterised, no DSN logging. Same as TM-D2. |
| mypy strict on `Literal["RealTime", ...]`. | Already supported (TM-D2 uses `Mode` literal in `schemas.py`). |

## 10. Confirmation gate

Before starting Phase 3:

1. Read `.claude/specs/TM-D3-research.md` and this plan side-by-side.
2. Confirm the dbt target schema is `analytics` (already verified;
   `dbt/profiles.yml` declares `schema: analytics`).
3. Confirm the existing TM-D2 test fakes accept multi-batch inputs
   (verified; `FakeAsyncConnection.batches` is a list and pops in
   order — unit tests for `/reliability` already exercise the
   two-batch pattern).

If reality diverges from the plan, stop and report:

> *Expected: X. Found: Y. How should I proceed?*
