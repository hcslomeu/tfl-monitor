# TM-C3 — Research (Phase 1)

Read-only survey of the codebase before planning the remaining marts +
dbt exposures. Acceptance criteria from `SETUP.md` §7.3:

> Build disruption and bus marts with tests and dbt exposures.

Plus the C2-deferred C-dbt items the team-lead handed over:

- One-grain-above summary mart for line-status reliability
  (`pct_good_service` + `longest_disruption_window_minutes`).
- Exposures wiring marts to the API endpoints that consume them.

Linear: TM-10.

---

## 1. Inputs already on disk

### 1.1 Frozen Pydantic contracts (no edits this WP)

- `contracts/schemas/arrivals.py` — `ArrivalPayload` (frozen):
  `arrival_id`, `station_id`, `station_name`, `line_id`,
  `platform_name`, `direction`, `destination`, `expected_arrival`,
  `time_to_station_seconds`, `vehicle_id?`. Topic `"arrivals"`.
- `contracts/schemas/disruptions.py` — `DisruptionPayload` (frozen):
  `disruption_id`, `category` (`DisruptionCategory` enum),
  `category_description`, `description`, `summary`,
  `affected_routes` (`list[str]` of line ids), `affected_stops`
  (`list[str]` of station ids), `closure_text`, `severity` (int ≥ 0),
  `created`, `last_update`. Topic `"disruptions"`.
- `contracts/schemas/common.py` — `Event[P]` envelope and the
  `DisruptionCategory` StrEnum (`RealTime | PlannedWork | Information |
  Incident | Undefined`).
- `contracts/dbt_sources.yml` ↔ `dbt/sources/tfl.yml` already declare
  the three append-only Kafka-backed sources (`tfl.line_status`,
  `tfl.arrivals`, `tfl.disruptions`) and the two `ref` tables
  (`tfl.lines`, `tfl.stations`). No edits needed here.

### 1.2 Raw Postgres tables (frozen — created by TM-A1)

`contracts/sql/001_raw_tables.sql` declares the three raw tables with
identical envelope shape:

```sql
event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
event_type  TEXT NOT NULL,
source      TEXT NOT NULL,
payload     JSONB NOT NULL
```

GIN index on `payload`, BTREE on `ingested_at DESC` for all three
(`003_indexes.sql`).

### 1.3 Producer cadences

- Line-status: `LINE_STATUS_POLL_PERIOD_SECONDS = 30.0`
  (`src/ingestion/producers/line_status.py`). Already encoded into
  `mart_tube_reliability_daily.minutes_observed_estimate`.
- Arrivals + Disruptions: TM-B4 in flight; the plan locks defaults
  from `TM-B4-plan.md`. We do **not** depend on actual cadence
  numbers in TM-C3 marts — bus + disruption KPIs use timestamp deltas
  / counts rather than coverage estimates, so no constant has to live
  in two places.

### 1.4 Already-shipped dbt artefacts (TM-C1 + TM-C2 in `main`)

- `dbt_project.yml`: staging = view, intermediate = view, marts =
  table; `model-paths: ["models", "sources"]`.
- `dbt/models/staging/stg_line_status.sql` (incremental `merge` on
  `event_id`, 5 min lookback, DESC dedup, `on_schema_change=fail`).
- `dbt/models/staging/schema.yml` (column docs + generic tests for
  `stg_line_status`).
- `dbt/models/marts/mart_tube_reliability_daily.sql` (table; grain
  `(line_id, calendar_date, status_severity)`).
- `dbt/models/marts/schema.yml` (column docs + generic tests for the
  mart).
- `dbt/tests/assert_status_severity_known.sql` and
  `dbt/tests/assert_mart_tube_reliability_daily_grain.sql`.

The structural hooks (model paths, test paths, exposures path
discovery) are all working. New artefacts slot in alongside.

### 1.5 API endpoints that will consume the marts (for exposures)

From `contracts/openapi.yaml`:

| Endpoint | operationId | Mart it should consume |
|---|---|---|
| `GET /api/v1/status/live` | `get_status_live` | `mart_tube_reliability_daily` (latest snapshot per line) |
| `GET /api/v1/status/history` | `get_status_history` | `mart_tube_reliability_daily` |
| `GET /api/v1/reliability/{line_id}` | `get_line_reliability` | `mart_tube_reliability_daily_summary` (primary), `mart_tube_reliability_daily` (drilldown) |
| `GET /api/v1/disruptions/recent` | `get_recent_disruptions` | `mart_disruptions_daily` |
| `GET /api/v1/bus/{stop_id}/punctuality` | `get_bus_punctuality` | `mart_bus_metrics_daily` |
| `POST /api/v1/chat/stream` + `/api/v1/chat/history/...` | agent endpoints | n/a (not warehouse-backed) |

Exposures cover the five warehouse-backed endpoints. The chat
endpoints are not exposures — they live in a future RAG mart (TM-D5+)
or directly off Pinecone.

---

## 2. New marts in scope

### 2.1 `mart_tube_reliability_daily_summary` — unblocked, ships first

Grain: `(line_id, calendar_date)`. **One row per line per day.**
Direct rollup of `mart_tube_reliability_daily`.

| Column | Source | Notes |
|---|---|---|
| `line_id` | mart_tube_reliability_daily | grain |
| `line_name` | `min(line_name)` | denormed |
| `mode` | `min(mode)` | denormed |
| `calendar_date` | mart_tube_reliability_daily | grain |
| `total_snapshots` | `sum(snapshot_count)` | total observations for the day |
| `good_service_snapshots` | `sum(snapshot_count) FILTER (WHERE status_severity = 10)` | severity 10 = `GOOD_SERVICE` |
| `pct_good_service` | `good_service_snapshots / total_snapshots`, rounded to 4 d.p. | always in `[0, 1]` |
| `minutes_observed_estimate` | `sum(minutes_observed_estimate)` | wall-clock coverage estimate |
| `longest_disruption_window_minutes` | gaps-and-islands over `stg_line_status` | max contiguous run of `status_severity != 10` × 30 s |

`longest_disruption_window_minutes` cannot be computed from
`mart_tube_reliability_daily` (which has lost ordering). The summary
mart re-reads `stg_line_status` for that one column. Standard
"row_number diff" gaps-and-islands pattern in Postgres:

```sql
with tagged as (
    select line_id, ingested_at,
        case when status_severity = 10 then 0 else 1 end as is_disrupted,
        date_trunc('day', ingested_at at time zone 'UTC')::date as calendar_date
    from {{ ref('stg_line_status') }}
),
runs as (
    select line_id, calendar_date, is_disrupted,
        row_number() over (partition by line_id, calendar_date            order by ingested_at)
      - row_number() over (partition by line_id, calendar_date, is_disrupted order by ingested_at)
        as run_id
    from tagged
)
select line_id, calendar_date,
    coalesce(max(case when is_disrupted = 1 then count(*) end), 0)
        * 30.0 / 60.0 as longest_disruption_window_minutes
from runs
group by line_id, calendar_date
```

(Phase 2 will lock the final SQL; the snippet here is illustrative.)

### 2.2 `mart_disruptions_daily` — needs `raw.disruptions` populated

Disruptions naturally fan out via `affected_routes` (list of line
ids). The mart unnests that array so a single disruption affecting
N lines counts on each line's row.

Grain candidates:

- (a) `(calendar_date, line_id)` — one row per (day, affected line).
- (b) `(calendar_date, category, line_id)` — splits by disruption
  category (`RealTime | PlannedWork | …`).

**Recommendation**: start with (a). The category breakdown can be
emitted as a separate column (`distinct_categories` array, plus
`max_severity`) without inflating the grain. If TM-D3 later needs a
category-by-category timeline, TM-C4 can carve a sibling mart.

| Column | Source | Notes |
|---|---|---|
| `line_id` | unnest(`payload.affected_routes`) | grain |
| `calendar_date` | `date_trunc('day', ingested_at AT TIME ZONE 'UTC')` | grain |
| `disruption_count` | `count(distinct disruption_id)` | dedup across snapshots — same disruption may be ingested many times |
| `distinct_categories` | `array_agg(distinct category order by category)` | overview of category mix |
| `max_severity` | `max(severity)` | worst severity seen for that (day, line) |
| `first_seen_at` | `min(ingested_at)` | when we first saw any disruption affecting the line that day |
| `last_seen_at` | `max(ingested_at)` | most recent ingest |

The TM-B1 normaliser synthesises `created` / `last_update` to `now()`
(documented in `TM-B4-research.md`); we therefore do **not** model
"minutes_active" from those fields — we use `ingested_at` deltas
instead.

### 2.3 `mart_bus_metrics_daily` — needs `raw.arrivals` populated

`ArrivalPayload` does not carry a `mode`; we filter to bus lines via
a join against `ref.lines` (or hard-coded list). `ref.lines` is a
declared source (`schema=ref`) but is currently unpopulated until
TM-A2 lands the static-ingest DAG. **Decision**: use the
`ArrivalPayload.line_id` and an inline `WHERE line_id IN (SELECT
line_id FROM {{ source('tfl', 'lines') }} WHERE mode = 'bus')`. If
`ref.lines` is empty at run time (current state), the mart correctly
emits zero rows — no error, no fake data.

Grain: `(calendar_date, line_id, station_id)` — bus lines only. The
`/api/v1/bus/{stop_id}/punctuality` endpoint queries by `stop_id`, so
the per-station dimension belongs here.

| Column | Source | Notes |
|---|---|---|
| `line_id` | `payload.line_id` | grain |
| `station_id` | `payload.station_id` | grain |
| `calendar_date` | `date_trunc('day', ingested_at AT TIME ZONE 'UTC')` | grain |
| `prediction_count` | `count(*)` | total arrival predictions |
| `distinct_vehicles` | `count(distinct vehicle_id) FILTER (WHERE vehicle_id IS NOT NULL)` | how many distinct buses passed |
| `avg_time_to_station_seconds` | `avg(time_to_station_seconds)` | how far ahead we typically saw each prediction |
| `min_time_to_station_seconds` | `min(time_to_station_seconds)` | tightest prediction window |
| `max_time_to_station_seconds` | `max(time_to_station_seconds)` | loosest prediction window |
| `first_predicted_arrival` | `min(expected_arrival)` | day boundary anchor |
| `last_predicted_arrival` | `max(expected_arrival)` | day boundary anchor |

Out of scope: a true "punctuality" KPI (predicted vs actual). TfL's
unified API does not publish actual departure events; the
`/punctuality` endpoint will compute a freshness proxy (e.g. how many
predictions matured within ±60 s of `expected_arrival`) downstream
from this mart. TM-C3 surfaces the building blocks.

---

## 3. Staging additions

### 3.1 `stg_arrivals.sql` — new

Mirrors `stg_line_status` shape: incremental `merge` on `event_id`,
5-minute lookback, DESC dedup, `on_schema_change=fail`. Filter
`event_type = 'arrivals.snapshot'` (TM-B4 plan locks this literal).
Unnest `ArrivalPayload` into typed columns. Tests: `not_null` on
`event_id`, `arrival_id`, `station_id`, `line_id`, `expected_arrival`;
`unique` on `event_id`.

### 3.2 `stg_disruptions.sql` — new

Same shape. Filter `event_type = 'disruptions.snapshot'`. Unnest
`DisruptionPayload`, including `affected_routes` and `affected_stops`
as JSONB arrays — leave the unnesting to the mart, where the fan-out
matters. Tests: `not_null` on `event_id`, `disruption_id`, `category`,
`severity`; `unique` on `event_id`; `accepted_values` on `category`
mirroring the `DisruptionCategory` enum.

The `stg_line_status` `unique` test on `event_id` is currently a
no-op in steady state (raw PK enforces uniqueness). Same behaviour
here — defensive only.

---

## 4. Exposures

dbt exposures live under `model-paths` (or any `paths`) and are
discovered via `*.yml` files containing top-level `exposures:`. The
project doesn't have an exposures file yet; the cleanest place is
`dbt/models/exposures.yml` (same dir-tier as the model schema files).

For each warehouse-backed API endpoint:

```yaml
exposures:
  - name: api_status_live
    type: application
    url: https://tfl-monitor-api.example/api/v1/status/live
    description: "Latest line-status snapshot per line."
    depends_on:
      - ref('mart_tube_reliability_daily')
    owner:
      name: tfl-monitor-api
      email: ops@tfl-monitor.invalid
```

Five exposures total (one per warehouse-backed endpoint). `owner.email`
is a synthetic placeholder — the project has no shared inbox; the
field is required by dbt schema. The same placeholder is used across
all exposures so it is grep-able.

---

## 5. Custom tests

Existing pattern (one custom SQL file per concern, no `dbt_utils`):

| File | Purpose |
|---|---|
| `dbt/tests/assert_pct_good_service_bounded.sql` | mart summary: `pct_good_service` strictly in `[0, 1]` |
| `dbt/tests/assert_mart_tube_reliability_daily_summary_grain.sql` | composite uniqueness on `(line_id, calendar_date)` |
| `dbt/tests/assert_mart_disruptions_daily_grain.sql` | composite uniqueness on `(calendar_date, line_id)` |
| `dbt/tests/assert_mart_bus_metrics_daily_grain.sql` | composite uniqueness on `(calendar_date, line_id, station_id)` |
| `dbt/tests/assert_disruption_category_known.sql` | `category` strictly in the `DisruptionCategory` enum (mirrors the Pydantic enum without forcing every consumer to re-read it) |

---

## 6. Validation

- `uv run task dbt-parse` — CI gate. Will pass with empty raw tables.
- `uv run task lint` / `uv run task test` — green; no Python touched.
- `uv run dbt build --project-dir dbt --profiles-dir dbt --target dev`
  — local manual command, requires Compose stack up. Tests on empty
  `raw.{arrivals,disruptions}` will pass trivially. Once TM-B4 lands
  and rows arrive, the same `dbt build` exercises the real KPI
  computation.
- `make check` — must stay green.

---

## 7. Dependency on TM-B4

TM-B4 is in flight on b-track (specs visible in `.claude/specs/TM-B4-*`
in the shared workspace; raw shape locked, contracts already frozen).
Three implications for TM-C3:

1. **No source contract risk.** `ArrivalPayload` /
   `DisruptionPayload` are frozen, so the staging unnests are safe to
   write today.
2. **Live data risk.** Without TM-B4's consumers writing rows, the new
   marts compile to empty tables and `dbt build` is a smoke. Real
   numerical validation arrives only after B4 lands and ingestion runs
   for at least one full day. That is an acceptance footnote for the
   PR body, not a blocker.
3. **PR strategy.** Per the team-lead handoff, ship all of TM-C3 in a
   single PR (CLAUDE.md "One WP, one PR"). The summary mart goes in
   first (already unblocked); the disruption + bus marts ride along.
   If B4 stalls, the PR is still mergeable — the affected marts
   simply have no rows yet; the contracts that drive them are frozen.

---

## 8. Open questions for Phase 2

1. **Q1 — Mart materialisation**: keep project default (`table`) for
   all three? *Recommendation*: yes, same reasoning as TM-C2 (low
   cardinality at a daily grain, full-refresh is cheap).
2. **Q2 — Summary mart consumption**: read from
   `mart_tube_reliability_daily` for ratios + from `stg_line_status`
   for `longest_disruption_window_minutes`, or read `stg_line_status`
   for everything? *Recommendation*: read from
   `mart_tube_reliability_daily` for the ratios (it is already
   aggregated, lineage stays clean) and from `stg_line_status` for the
   gaps-and-islands. dbt-docs lineage shows both edges.
3. **Q3 — Bus filter source**: `ref.lines.mode = 'bus'` (correct,
   currently empty) or hard-coded `mode = 'bus'` literal? *Recommendation*:
   reference `source('tfl', 'lines')` so the dependency is explicit
   and `ref.lines` becomes the source of truth once TM-A2 lands.
4. **Q4 — Exposures owner**: shared synthetic email vs per-endpoint?
   *Recommendation*: single `tfl-monitor-api` owner for all five
   exposures. KISS; there is no team breakdown to encode.
5. **Q5 — Disruption category breakdown**: separate column or split
   the grain? *Recommendation*: column (`distinct_categories` array +
   `max_severity`). Splitting the grain would inflate row count
   without delivering KPIs the API actually needs.
6. **Q6 — Bus mart grain — include `station_id`?**: yes — the
   `/api/v1/bus/{stop_id}/punctuality` endpoint hits a station-level
   API, so the mart needs that dimension exposed.
7. **Q7 — Custom test for `severity` bounded?**: TM-B1 normaliser
   doesn't bound `severity` (only `≥ 0` in the Pydantic model).
   *Recommendation*: skip a `severity ≤ N` test; we don't have a
   ceiling from TfL.
8. **Q8 — Schema docs filename convention**: per-mart
   `dbt/models/marts/<mart>.yml` (one file per mart) vs single
   `dbt/models/marts/schema.yml`? *Recommendation*: keep the
   single-file pattern set by TM-C2 (`schema.yml`). Same for staging.
   Extending the existing files is simpler than fragmenting.
9. **Q9 — PR slicing**: ship all of TM-C3 in one PR. *Recommendation*:
   yes — team-lead handoff explicitly anchored on "One WP, one PR".
   If B4 ships first, no waiting. If B4 stalls, the C3 PR still
   merges; affected marts return empty rows.

Phase 2 plan locks these and writes the file-by-file breakdown.
