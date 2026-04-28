# TM-D3 — Research (Phase 1)

Read-only investigation pass for **TM-D3: Remaining endpoints
(disruptions, bus)**. This file is a list of facts, options, and open
questions. Design decisions are committed in `TM-D3-plan.md`
(Phase 2). The shape mirrors `TM-D2-research.md`.

## 1. Charter

`PROGRESS.md` row + Linear `TM-14`:

> TM-D3 — *Remaining endpoints (disruptions, bus)* — track
> `D-api-agent`, depends on TM-C3, phase 4.
> *`/disruptions` wired to disruption marts; `/bus/*` wired to
> `mart_bus_metrics_daily`; all queries parameterised; endpoint tests
> against real Postgres pass; OpenAPI spec matches implementation.*

No `.claude/specs/TM-D3-spec.md` exists. Acceptance criteria are
derived from:

- `contracts/openapi.yaml` (frozen tier-1 contract).
- `tests/api/test_stubs.py::STUB_ROUTES` rows hint-keyed `TM-D3`.
- TM-D2 research/plan as the architectural reference (lifespan,
  pool, `_problem`, fakes, schema-qualified `analytics.*`).
- TM-C3 mart layer and exposure documentation (`dbt/models/exposures.yml`).

## 2. Surface in scope

Two routes flagged with the `TM-D3` hint in `STUB_ROUTES`:

| Method | Path | OpenAPI operationId | Handler today |
|---|---|---|---|
| GET | `/api/v1/disruptions/recent` | `get_recent_disruptions` | `_not_implemented("Not implemented — see TM-D3")` |
| GET | `/api/v1/bus/{stop_id}/punctuality` | `get_bus_punctuality` | same |

Out of scope (still 501 after TM-D3):

- `/api/v1/chat/stream`, `/api/v1/chat/{thread_id}/history` → TM-D5.
- `/health` is implemented; `dependencies` payload is empty (revisit
  in TM-D5/TM-A5).

## 3. Response shapes (frozen)

From `contracts/openapi.yaml`:

### `Disruption` (used by `/disruptions/recent`)

| Field | Type | Notes |
|---|---|---|
| `disruption_id` | string | required |
| `category` | enum | `RealTime`, `PlannedWork`, `Information`, `Incident`, `Undefined` |
| `category_description` | string | required |
| `description` | string | required |
| `summary` | string | required |
| `affected_routes` | string[] | required |
| `affected_stops` | string[] | required |
| `closure_text` | string | required (empty string allowed) |
| `severity` | int ≥ 0 | required |
| `created` | RFC 3339 datetime | required |
| `last_update` | RFC 3339 datetime | required |

### `BusPunctuality` (used by `/bus/{stop_id}/punctuality`)

| Field | Type | Notes |
|---|---|---|
| `stop_id` | string | required |
| `stop_name` | string | required |
| `window_days` | int 1–90 | required |
| `on_time_percent` | number 0–100 | required |
| `early_percent` | number 0–100 | required |
| `late_percent` | number 0–100 | required |
| `sample_size` | int ≥ 0 | required |

### Query parameters

- `/api/v1/disruptions/recent`:
  - `limit`: optional int 1–200, default 50.
  - `mode`: optional enum string (same as `LineStatus.mode`).
- `/api/v1/bus/{stop_id}/punctuality`:
  - Path: `stop_id` (string, required).
  - **No query parameters declared.** `window_days` is response-only;
    Phase 2 must lock the window value (default to 7 to match the
    OpenAPI example).

Errors use RFC 7807 `application/problem+json` (already in
`components.responses.Problem`).

## 4. Data layer (TM-C3 already in `main`)

### `analytics.stg_disruptions`

Source: `dbt/models/staging/stg_disruptions.sql`. Incremental on
`event_id`, 5-minute lookback, `on_schema_change=fail`. Typed columns:

```
event_id, ingested_at, event_type, source,
disruption_id, category, category_description,
description, summary, closure_text, severity,
created, last_update,
affected_routes  -- JSONB array of line_id strings
affected_stops   -- JSONB array of NaPTAN ids
```

`closure_text` is `NULLIF(... ,'')`-coalesced, so the staging column
is nullable; the API contract requires the field as a non-nullable
string — Phase 2 must `COALESCE(closure_text, '')` at query time.

### `analytics.mart_disruptions_daily`

Source: `dbt/models/marts/mart_disruptions_daily.sql`. Grain
`(calendar_date, line_id)` after fanning out `affected_routes` via
`jsonb_array_elements_text`. Columns:

```
calendar_date, line_id,
disruption_count, distinct_categories (text[]),
max_severity, first_seen_at, last_seen_at
```

Aggregated, **without** the snapshot-level fields the OpenAPI
`Disruption` schema requires (no `description`, no `summary`, no
`affected_stops`, no `closure_text`, no `created`, no `last_update`).

### `analytics.mart_bus_metrics_daily`

Source: `dbt/models/marts/mart_bus_metrics_daily.sql`. Grain
`(calendar_date, line_id, station_id)`, filtered to bus lines via
`source('tfl', 'lines')` (mode = 'bus'). Columns:

```
calendar_date, line_id, station_id,
prediction_count, distinct_vehicles,
avg_time_to_station_seconds, min_time_to_station_seconds,
max_time_to_station_seconds,
first_predicted_arrival, last_predicted_arrival
```

`ref.lines` is empty until TM-A2/TM-A3 lands the static-ingest DAG;
the inner join therefore returns zero rows on a fresh database. The
exposure entry in `dbt/models/exposures.yml` documents this and
explicitly tags the mart as *"prediction freshness building blocks"*
— the API endpoint must compose the punctuality output on top of
these columns.

### `analytics.stg_arrivals`

Source: `dbt/models/staging/stg_arrivals.sql`. Typed columns:

```
event_id, ingested_at, event_type, source,
arrival_id, station_id, station_name, line_id,
platform_name, direction, destination,
expected_arrival, time_to_station_seconds, vehicle_id
```

`station_name` is the only place `stop_name` (required by the OpenAPI
`BusPunctuality.stop_name`) is materialised in the warehouse. The bus
mart does not denormalise it.

## 5. App layer (already in `main` — TM-D2)

Reuse-only checklist:

- `src/api/main.py` already ships:
  - `lifespan` reading `DATABASE_URL` (no-op when unset).
  - `app.state.db_pool` (or `None`).
  - `_problem(status, title, detail)` helper emitting
    `application/problem+json`.
  - `_not_implemented(detail)` for the two TM-D3 routes (still 501).
  - `Problem` Pydantic model in `src/api/schemas.py`.
  - CORS allowlist (`http://localhost:3000`,
    `https://tfl-monitor.vercel.app`).
- `src/api/db.py` already ships:
  - `build_pool(dsn)` factory (`min_size=1, max_size=4`).
  - SQL constants and async fetchers for the three D2 endpoints.
- `tests/conftest.py` ships `FakeAsyncCursor`, `FakeAsyncConnection`,
  `FakeAsyncPool`, `fake_pool_factory`, `attach_pool` — TM-D3 unit
  tests should reuse these without forking.

## 6. Recent disruptions — source choice

`mart_disruptions_daily` is the wrong source: it lacks every
snapshot-level field the OpenAPI contract requires.
`stg_disruptions` is the correct source — event-grained with all
required fields, plus `last_update` and `created` for the recency
sort.

The `dbt/models/exposures.yml` entry for `api_recent_disruptions`
already lists both `stg_disruptions` and `mart_disruptions_daily` as
dependencies and documents:

> *"Snapshot-level fields (description, summary, affected_stops,
> created, last_update) come from stg_disruptions; mart_disruptions_daily
> provides the daily aggregate (count, max_severity)."*

So the exposure already foresaw the snapshot-level pull from staging.
Phase 2 reads from `analytics.stg_disruptions` only.

### Sort and limit

`/disruptions/recent` is "most recent first". `last_update` is the
freshness signal (`created` can be days old for `PlannedWork` while
`last_update` advances as TfL re-publishes). Sort
`ORDER BY last_update DESC NULLS LAST, ingested_at DESC`. The
`ingested_at` tiebreaker keeps ordering stable when `last_update` ties
(plausible for synthesised timestamps — the TfL normaliser stamps both
to `now()` when TfL omits them; see `mart_disruptions_daily.sql`
header comment).

Apply `LIMIT %(limit)s` after sorting; `limit` is bound 1–200 by
FastAPI `Query(..., ge=1, le=200)`.

### Mode filter

OpenAPI declares `mode` as a string with enum
`[tube, elizabeth-line, overground, dlr, bus, national-rail,
river-bus, cable-car, tram]`. The disruption record itself carries
`affected_routes` (line_id list) but no mode. `ref.lines` would be
the natural source of truth but is empty until TM-A2/TM-A3.

Three options for filtering:

- **A.** No filter — ignore `mode`. Rejected — contract says it filters.
- **B.** Subquery against `analytics.stg_line_status` (which is populated
  by the line-status producer — TM-B2/B3 are live in main):
  `EXISTS (SELECT 1 FROM analytics.stg_line_status sls WHERE
  sls.mode = %(mode)s AND sls.line_id IN
  (SELECT jsonb_array_elements_text(d.affected_routes)))`. Works
  today; degrades gracefully if `stg_line_status` is empty (no rows
  match) but that is the same degradation as everywhere else.
- **C.** Wait for `ref.lines` (TM-A3). Too pessimistic — TM-D3 must
  ship before then.

Recommendation: **B**, with the subquery cached at the SQL level (so
the planner can use the already-existing index on `stg_line_status`).

### Recency window

Path is `/recent` not `/history`. Lean: do not add a soft
`last_update >= now() - INTERVAL 'X'` window. `LIMIT` plus `ORDER BY
last_update DESC` is sufficient — the caller decides how recent
"recent" is by varying `limit`. Adding a window adds a knob and a
risk (empty result during a quiet network) without solving anything.

## 7. Bus punctuality — divergence from contract

Hard divergence between the OpenAPI contract and the warehouse:

- Contract requires `on_time_percent`, `early_percent`,
  `late_percent`, `stop_name`, `window_days`, `sample_size` for a
  given `stop_id`.
- `mart_bus_metrics_daily` only exposes
  `prediction_count, distinct_vehicles, avg/min/max_time_to_station_seconds,
  first/last_predicted_arrival`. It has zero notion of
  on-time/early/late, and zero `stop_name` denormalisation.
- TfL **does not publish actual departure events** — only arrival
  *predictions* — so a true punctuality KPI cannot be computed from
  what we ingest. The exposure documents this as
  *"freshness building blocks; the API composes the proxy"*.

### Resolution: API-side proxy on top of `time_to_station_seconds`

The endpoint must compose a *proxy* using prediction-grain rows. The
only signal in `stg_arrivals` that can drive an "on-time / early /
late" classification is `time_to_station_seconds` — the predicted
seconds-until-arrival at the stop, sampled by the producer every
30 s.

Three buckets, documented in the SQL:

- `late`: `time_to_station_seconds < 0` — bus should already have
  arrived but the prediction persists; proxy for "running late".
- `on_time`: `0 <= time_to_station_seconds <= 300` — bus visible in
  a five-minute window; proxy for "arriving on time".
- `early`: `time_to_station_seconds > 300` — prediction shows the
  bus more than five minutes out; proxy for "scheduled / not yet
  due".

Five minutes is the TfL-published target for bus punctuality
("Bus performance — within 5 minutes of schedule" — TfL Annual Report
2023/24). Using the same threshold keeps the proxy aligned with the
public KPI even though the underlying signal is different.

The bucket boundaries are encoded as SQL constants and called out in
the docstring + the PR description so the reviewer (and a future
agent generating SQL via TM-D5) understands this is a proxy, not a
ground-truth KPI.

### `stop_name`

`mart_bus_metrics_daily` does not denormalise `station_name`. The
endpoint must therefore either:

- **A.** Read `station_name` from `analytics.stg_arrivals` (where it
  is denormalised by `stg_arrivals`).
- **B.** Add `station_name` to `mart_bus_metrics_daily` — out of
  scope (touches `dbt/`, owned by the C-dbt track).

Lean: **A**. One additional query against `stg_arrivals` filtered by
`station_id`, `LIMIT 1`. Keep the proxy + name composition in the
fetcher.

### `window_days`

OpenAPI does not declare a `window` query param. Lean: hard-code
**7** (matches the OpenAPI example). Echo into `window_days` in the
response.

### Source: `stg_arrivals` not `mart_bus_metrics_daily`

The mart filters by `mode = 'bus'` against the empty `ref.lines`,
returning zero rows on a fresh database — which would make every
call return 404. The endpoint instead reads from `stg_arrivals`
directly:

- The proxy buckets need raw `time_to_station_seconds`, not the
  pre-aggregated mean/min/max.
- `station_name` lives in `stg_arrivals` only.
- The bus filter — `arrivals` is a multi-mode topic (TfL StopPoint
  arrivals) — must come from another signal. The cleanest is to
  filter by `station_id` in the path, which is intrinsically
  bus-scoped (NaPTAN ids beginning with `490*` are TfL bus stops).
  The endpoint trusts the caller's `stop_id` is a bus stop; if it
  is not, the result is empty (no arrivals records → 404).

### Empty result → 404

When `ref.lines` is empty (today) the mart is empty; `stg_arrivals`
is also empty until TM-B4 starts producing. In either case the
endpoint must return RFC 7807 **404** with detail
`"No punctuality data for stop {stop_id}"`. Document this clearly in
the docstring and PR description so reviewers do not mistake the
404 for a bug.

## 8. Pydantic response models

Add to `src/api/schemas.py`:

- `DisruptionResponse(BaseModel)` — eight required fields per §3,
  `extra="forbid"`. `category` typed as `Literal[...]` matching the
  OpenAPI enum.
- `BusPunctualityResponse(BaseModel)` — seven required fields per §3,
  `extra="forbid"`. Numeric fields bounded
  `Field(ge=0.0, le=100.0)` for the percents and `Field(ge=0)` for
  `sample_size` and `window_days` (`ge=1, le=90`).

Naming follows the TM-D2 convention (`*Response` suffix to
disambiguate from any future Kafka tier-2 model).

## 9. SQL — drafts (final form locked in plan)

### `/disruptions/recent`

```sql
SELECT
    disruption_id,
    category,
    category_description,
    description,
    summary,
    COALESCE(closure_text, '')                AS closure_text,
    severity,
    created,
    last_update,
    affected_routes,                          -- JSONB; cast in Python
    affected_stops                            -- JSONB; cast in Python
FROM analytics.stg_disruptions
WHERE event_type = 'disruptions.snapshot'
  AND (
      %(mode)s IS NULL
      OR EXISTS (
          SELECT 1
          FROM analytics.stg_line_status sls
          WHERE sls.mode = %(mode)s
            AND sls.line_id IN (
                SELECT jsonb_array_elements_text(stg_disruptions.affected_routes)
            )
      )
  )
ORDER BY last_update DESC NULLS LAST, ingested_at DESC
LIMIT %(limit)s
```

`affected_routes` and `affected_stops` are JSONB arrays in staging;
psycopg returns them as Python lists when cursor row factory is
`dict_row` — Pydantic accepts the `list[str]` directly.

### `/bus/{stop_id}/punctuality` — punctuality buckets

```sql
SELECT
    COUNT(*)::int AS sample_size,
    COUNT(*) FILTER (
        WHERE time_to_station_seconds < 0
    )::int AS late_count,
    COUNT(*) FILTER (
        WHERE time_to_station_seconds BETWEEN 0 AND 300
    )::int AS on_time_count,
    COUNT(*) FILTER (
        WHERE time_to_station_seconds > 300
    )::int AS early_count
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

Two queries on one connection checkout, exactly mirroring the
TM-D2 `/reliability` two-query pattern.

## 10. Fetcher signatures

```python
async def fetch_recent_disruptions(
    pool: AsyncConnectionPool,
    *,
    limit: int,
    mode: str | None,
) -> list[DisruptionResponse]: ...

async def fetch_bus_punctuality(
    pool: AsyncConnectionPool,
    *,
    stop_id: str,
    window: int,
) -> BusPunctualityResponse | None: ...
```

`fetch_bus_punctuality` returns `None` when:

- The aggregate query returns `sample_size == 0`, **or**
- The `stop_name` lookup returns no row (no arrivals ever ingested
  for that stop).

The handler maps `None` → 404 problem.

## 11. Test strategy

Mirroring TM-D2's three-tier approach.

### Unit (default `uv run task test`)

Two new files:

- `tests/api/test_disruptions_recent.py`:
  - Happy path: rows materialise into `DisruptionResponse`; SQL +
    params recorded match expectations.
  - Empty result: `200 []`.
  - Pool missing: `503` problem.
  - `limit=0` and `limit=201`: FastAPI emits `422` (default).
  - `mode=invalid`: FastAPI emits `422` (Literal validator).
  - `mode=tube` filter: SQL params show `mode="tube"` passed through.
- `tests/api/test_bus_punctuality.py`:
  - Happy path: punctuality buckets sum correctly to 100; SQL +
    params recorded; `stop_name` echoed.
  - Pool missing: `503` problem.
  - Empty arrivals: `404` problem.
  - Zero `sample_size` (covers boundary): `404` problem.
  - `window_days = 7` is hard-coded (assert on response).

### Drift / contract

`tests/api/test_stubs.py`: drop the two TM-D3 rows from
`STUB_ROUTES`. The bidirectional drift checks must keep passing.

### Integration (`-m integration`, gated on `DATABASE_URL`)

Two new files mirroring `tests/integration/test_status_*.py`:

- `tests/integration/test_disruptions_recent.py`: insert rows
  directly into `analytics.stg_disruptions`; create the table if it
  does not exist (same pattern as TM-D2 integration tests).
- `tests/integration/test_bus_punctuality.py`: insert rows directly
  into `analytics.stg_arrivals`. Two scenarios: happy path with
  bucketed counts, and unknown stop returns 404.

## 12. Risks / surprises

1. **Bus punctuality is a documented proxy, not a ground-truth KPI.**
   The handler docstring + PR description must be explicit. A future
   reader who sees `on_time_percent: 88.5` should not believe TfL
   buses are 88.5% on-time today — the number reflects the
   distribution of `time_to_station_seconds` predictions, not actual
   arrivals. Surface this in the docstring and the PR body.
2. **`stg_disruptions` is empty until TM-B4 ingests + dbt runs.**
   Same pattern as TM-D2: integration tests seed staging directly
   (bypassing dbt). Production traffic against the endpoint will
   return `[]` until the producer + consumer + dbt are running.
3. **`stg_line_status` may be empty in some integration test DBs.**
   The `EXISTS` subquery for the `mode` filter degrades to "matches
   nothing" when the staging table is empty; tests must either skip
   `mode=...` cases or seed `stg_line_status` alongside
   `stg_disruptions`. Lean: integration tests for `mode=...` filtering
   are unit tests against the fake pool; the real-Postgres test
   exercises only the `mode IS NULL` path.
4. **`closure_text` nullability mismatch.** Staging's
   `closure_text` is nullable (NULLIF). API contract requires non-null
   string. SQL `COALESCE(closure_text, '')` resolves it.
5. **`affected_routes` / `affected_stops` JSONB serialisation.**
   psycopg with `dict_row` returns JSONB columns as Python lists.
   Pydantic `list[str]` accepts directly. No manual cast needed —
   verify in unit tests.
6. **Bucket boundaries on `time_to_station_seconds`.** A future
   reviewer may push back on the 0–300 s "on-time" definition. The
   choice is anchored to TfL's own 5-minute bus performance KPI —
   document the rationale in the SQL comment.
7. **NaPTAN scope.** The endpoint trusts the caller's `stop_id`. A
   tube station id passed in returns whatever arrivals (if any) are
   recorded — the punctuality numbers will still compute. This is a
   contract-honest behaviour: the response shape is satisfied; the
   "is it actually a bus stop?" check belongs in TM-A3 / `ref.lines`.
8. **Bandit on the SQL constants.** Strings, parameterised. No DSN
   logging. Same as TM-D2.

## 13. Open questions for Phase 2

1. **`/disruptions/recent` recency window.** Cap by `limit` only or
   add a soft `last_update >= now() - INTERVAL 'N'` filter? Lean:
   `limit` only. Path is `/recent`, not `/last_24h`.
2. **`mode` filter implementation.** Subquery against
   `stg_line_status` (Option B in §6) vs. waiting for `ref.lines`
   (rejected). Lean: subquery.
3. **Disruption source.** `stg_disruptions` (snapshot grain) vs.
   `mart_disruptions_daily` (daily aggregate). Lean: staging — the
   contract demands snapshot-level fields the mart does not expose.
4. **Bus source.** `mart_bus_metrics_daily` (empty until TM-A3) vs.
   `stg_arrivals` (event grain, has `station_name`,
   `time_to_station_seconds`). Lean: `stg_arrivals` — only
   workable source.
5. **Bucket definitions for on-time / early / late.** Lean: 0–300 s
   → on-time, > 300 s → early, < 0 s → late. Anchored to TfL's
   public 5-minute bus performance KPI. Document in SQL.
6. **`stop_name` source.** Lean: separate `stg_arrivals` lookup,
   `LIMIT 1` ordered by latest `ingested_at`. Two queries, one
   connection — same shape as `/reliability`.
7. **`window_days` for bus punctuality.** OpenAPI does not declare a
   `window` query param. Lean: hard-code **7** to match the
   OpenAPI example. No new query param.
8. **404 detail wording.** Lean: `"No punctuality data for stop
   {stop_id}"` and `"No reliability data for line ..."` (D2's
   wording extended to bus). Both follow the same pattern.
9. **Handler module layout.** Single `src/api/main.py`; SQL helpers
   in `src/api/db.py`. No `src/api/routes/` directory. Lean: keep
   flat — TM-D2 plan §4 explicitly forbids splitting.
10. **`get_pool` dependency.** Same as TM-D2: do not introduce a
    FastAPI `Depends(...)` helper. Handlers read
    `request.app.state.db_pool` directly.
11. **Mode filter on bus.** OpenAPI mode enum includes `bus`. Should
    `/disruptions/recent?mode=bus` work? Yes — `EXISTS` subquery
    against `stg_line_status` resolves naturally; the question is
    just *"are there any line_ids with mode='bus' in the warehouse?"*
    (yes, once bus producers run).

## 14. Acceptance criteria (proposed for Phase 2)

Working list — Phase 2 will lock these:

- [ ] `/api/v1/disruptions/recent` returns `Disruption[]` ordered by
      `last_update DESC NULLS LAST, ingested_at DESC`,
      `LIMIT %(limit)s` (1–200, default 50).
- [ ] `/api/v1/disruptions/recent` accepts `mode` filter; out-of-enum
      yields 422 (FastAPI default).
- [ ] `/api/v1/bus/{stop_id}/punctuality` returns `BusPunctuality`
      with `window_days = 7`, on-time/early/late percents derived as
      a documented proxy from `time_to_station_seconds`, sample_size
      = total predictions in the window.
- [ ] `/api/v1/bus/{stop_id}/punctuality` returns 404 RFC 7807 when
      no arrivals have been ingested for `stop_id` in the window.
- [ ] All SQL parameterised, named `%(name)s` placeholders, no
      f-strings, no string interpolation of caller input.
- [ ] Schema-qualified table names (`analytics.stg_disruptions`,
      `analytics.stg_arrivals`, `analytics.stg_line_status`).
- [ ] Pool optional: 503 problem when `app.state.db_pool` is None.
- [ ] CORS allowlist preserved (no widening).
- [ ] `tests/api/test_stubs.py::STUB_ROUTES` no longer lists the two
      TM-D3 routes.
- [ ] OpenAPI bidirectional drift checks remain green.
- [ ] `Pydantic v2` response models in `src/api/schemas.py` with
      `extra="forbid"`.
- [ ] Two new unit test files cover happy / empty / 503 / 422 / 404.
- [ ] Two new integration test files seed `stg_*` directly, gated on
      `DATABASE_URL`.
- [ ] `uv run task lint` (ruff + ruff format + mypy strict) green.
- [ ] `uv run task test` (default, hermetic) green.
- [ ] `uv run bandit -r src --severity-level high` reports nothing.
- [ ] `make check` green end-to-end.
- [ ] `PROGRESS.md` TM-D3 row marked ✅ with completion date.

## 15. Files expected to change in Phase 3

New:

- `tests/api/test_disruptions_recent.py`
- `tests/api/test_bus_punctuality.py`
- `tests/integration/test_disruptions_recent.py`
- `tests/integration/test_bus_punctuality.py`

Modified:

- `src/api/db.py` — add SQL constants and fetchers.
- `src/api/schemas.py` — add `DisruptionResponse`,
  `BusPunctualityResponse`.
- `src/api/main.py` — replace 501 stubs; reuse `_problem`,
  `request.app.state.db_pool`, the lifespan from D2.
- `tests/api/test_stubs.py` — drop the two TM-D3 rows from
  `STUB_ROUTES`.
- `PROGRESS.md` — flip the TM-D3 row to ✅.

Untouched (out of scope):

- `contracts/openapi.yaml` (frozen).
- `contracts/schemas/*` (Kafka tier).
- `dbt/` (mart layer owned by C-dbt; TM-C3 already in main).
- `web/` (E-frontend track; TM-E2 owns disruption log view).
- `src/ingestion/` (B-ingestion track).
- `airflow/` (A-infra track).
- `Makefile`, `docker-compose.yml`, `pyproject.toml`.
