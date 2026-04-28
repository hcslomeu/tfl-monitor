# TM-C3 — Implementation plan (Phase 2)

Source: `TM-C3-research.md`. All Phase-2 recommendations locked in as
**decisions** unless a sub-phase note overrides.

## Decisions

- **D1 — Mart materialisation**: project default `table` for all three
  new marts.
- **D2 — Summary-mart inputs**: ratios + counts from
  `mart_tube_reliability_daily` (already aggregated, clean lineage);
  `longest_disruption_window_minutes` from `stg_line_status`
  (gaps-and-islands needs ordered raw rows).
- **D3 — Bus mode filter**: `payload.line_id IN (SELECT line_id FROM
  {{ source('tfl', 'lines') }} WHERE mode = 'bus')`. `ref.lines` is
  empty until TM-A2 — until then the bus mart has zero rows, which is
  correct and dbt-test-clean.
- **D4 — Exposure owner**: single synthetic
  `tfl-monitor-api / ops@tfl-monitor.invalid` for all five exposures.
- **D5 — Disruption-category fan-out**: surface
  `distinct_categories` (sorted text array) and `max_severity` as
  columns; do **not** split the grain.
- **D6 — Bus-mart grain**: `(calendar_date, line_id, station_id)`.
- **D7 — `severity` bound test**: skipped (no upper bound from TfL).
- **D8 — Schema docs filename**: extend the existing
  `dbt/models/staging/schema.yml` and `dbt/models/marts/schema.yml`;
  no per-model fragmentation.
- **D9 — PR slicing**: single PR for all of TM-C3.
- **D10 — Worktree isolation**: work in
  `/tmp/c-track-worktree` (already created off `origin/main`). Saves
  the manual contamination dance from TM-C2.
- **D11 — Review-thread resolution rule**: per team-lead, **resolve
  threads only where a fix was applied**. Rejected threads stay open
  with the rationale reply visible — the human reviewer decides. (We
  override this only when the team-lead explicitly green-lights a
  resolve, e.g. to unblock a `required_review_thread_resolution: true`
  policy.) This lesson lands on the napkin alongside the C3 PR.

## Summary

Add three marts (`mart_tube_reliability_daily_summary`,
`mart_disruptions_daily`, `mart_bus_metrics_daily`), two staging
models (`stg_arrivals`, `stg_disruptions`), five custom singular
tests, five dbt exposures, and the corresponding column docs / generic
tests. No code outside `dbt/` changes (other than `PROGRESS.md`). CI
gate (`dbt-parse`) stays green; `dbt build` against local Compose +
populated raw tables exercises every test once TM-B4 has landed real
rows.

## Execution mode

- **Author of change**: single-track WP — execute serially in
  `/tmp/c-track-worktree`.
- **Branch**: `feature/TM-C3-remaining-marts` (already created).
- **PR title**: `feat(dbt): TM-C3 summary + disruptions + bus marts + exposures (TM-10)`.
- **PR body**: `Closes TM-10`; lists all eight new files + the two
  edits to existing schema files; flags the empty-rows behaviour
  while TM-B4 is still in flight; references the napkin update for
  the thread-resolution rule.

## What we're NOT doing

- Not editing `contracts/dbt_sources.yml` or `dbt/sources/tfl.yml`.
- Not adding `dbt_utils`. Singular SQL tests cover composite-grain
  uniqueness + bounded-ratio + accepted-values needs.
- Not modelling "minutes_active" for disruptions from `created` /
  `last_update` — those are synthesised to `now()` by TM-B1's
  normaliser (per `TM-B4-research.md`); use `ingested_at` deltas
  instead.
- Not building a true bus "punctuality" KPI (predicted vs actual) —
  TfL doesn't publish actual departure events. The mart surfaces the
  prediction-side building blocks; the API endpoint composes the
  freshness proxy.
- Not splitting the disruption mart by category. One sibling mart
  per category would inflate row count for no consumer gain.
- Not adding `dbt-build` / `dbt-test` to `taskipy` or `make check`.
  Both still require a live Postgres; CI gate stays at `dbt-parse`.
- Not wiring `/disruptions` or `/bus/*` endpoints — TM-D3.
- Not building the chat exposure — chat is not warehouse-backed.
- Not amending the existing `mart_tube_reliability_daily` mart
  (already in `main`); the summary mart consumes it.
- Not adding new pytest. Custom dbt tests run via `dbt build`.

## Sub-phases

### Phase 3.1 — `stg_disruptions.sql`

**File**: `dbt/models/staging/stg_disruptions.sql` (new)

Same shape as `stg_line_status`: incremental `merge` on `event_id`,
5-minute lookback, DESC dedup, `on_schema_change=fail`. Filter
`event_type = 'disruptions.snapshot'`. Unnest the `DisruptionPayload`
fields; keep `affected_routes` and `affected_stops` as JSONB arrays
for the mart to fan out.

```sql
{{
    config(
        materialized='incremental',
        unique_key='event_id',
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

with source as (
    select event_id, ingested_at, event_type, source, payload
    from {{ source('tfl', 'disruptions') }}
    where event_type = 'disruptions.snapshot'
    {% if is_incremental() %}
      and ingested_at >= coalesce(
          (select max(ingested_at) - interval '5 minutes' from {{ this }}),
          '-infinity'::timestamptz
      )
    {% endif %}
),

deduped as (
    select *,
        row_number() over (
            partition by event_id
            order by ingested_at desc
        ) as _rn
    from source
)

select
    event_id,
    ingested_at,
    event_type,
    source,
    (payload ->> 'disruption_id')::text                     as disruption_id,
    (payload ->> 'category')::text                          as category,
    (payload ->> 'category_description')::text              as category_description,
    (payload ->> 'description')::text                       as description,
    (payload ->> 'summary')::text                           as summary,
    (payload ->> 'closure_text')::text                      as closure_text,
    (payload ->> 'severity')::int                           as severity,
    (payload ->> 'created')::timestamptz                    as created,
    (payload ->> 'last_update')::timestamptz                as last_update,
    payload -> 'affected_routes'                            as affected_routes,
    payload -> 'affected_stops'                             as affected_stops
from deduped
where _rn = 1
```

### Phase 3.2 — `stg_arrivals.sql`

**File**: `dbt/models/staging/stg_arrivals.sql` (new)

Same incremental shape, filter `event_type = 'arrivals.snapshot'`.
Unnest `ArrivalPayload` into typed columns:

```sql
select
    event_id,
    ingested_at,
    event_type,
    source,
    (payload ->> 'arrival_id')::text                        as arrival_id,
    (payload ->> 'station_id')::text                        as station_id,
    (payload ->> 'station_name')::text                      as station_name,
    (payload ->> 'line_id')::text                           as line_id,
    (payload ->> 'platform_name')::text                     as platform_name,
    (payload ->> 'direction')::text                         as direction,
    (payload ->> 'destination')::text                       as destination,
    (payload ->> 'expected_arrival')::timestamptz           as expected_arrival,
    (payload ->> 'time_to_station_seconds')::int            as time_to_station_seconds,
    nullif(payload ->> 'vehicle_id', '')::text              as vehicle_id
from deduped
where _rn = 1
```

### Phase 3.3 — Staging schema docs + generic tests

Append two `models:` blocks to `dbt/models/staging/schema.yml`:

- `stg_disruptions`: `not_null` on `event_id`, `disruption_id`,
  `category`, `severity`, `ingested_at`, `created`, `last_update`;
  `unique` on `event_id`; `accepted_values` on `event_type`
  (`["disruptions.snapshot"]`) and `category` (the five
  `DisruptionCategory` enum values, all wrapped under `arguments:`
  per the dbt 1.11 syntax that TM-C2's PR established).
- `stg_arrivals`: `not_null` on `event_id`, `arrival_id`, `station_id`,
  `line_id`, `expected_arrival`, `time_to_station_seconds`,
  `ingested_at`; `unique` on `event_id`; `accepted_values` on
  `event_type` (`["arrivals.snapshot"]`).

### Phase 3.4 — `mart_tube_reliability_daily_summary.sql`

**File**: `dbt/models/marts/mart_tube_reliability_daily_summary.sql` (new)

Reads from `mart_tube_reliability_daily` (ratios + counts) and from
`stg_line_status` (gaps-and-islands). Final `select` joins the two
on `(line_id, calendar_date)`.

```sql
with daily_rollup as (
    select
        line_id,
        min(line_name) as line_name,
        min(mode) as mode,
        calendar_date,
        sum(snapshot_count) as total_snapshots,
        sum(snapshot_count) filter (where status_severity = 10)
            as good_service_snapshots,
        sum(minutes_observed_estimate) as minutes_observed_estimate
    from {{ ref('mart_tube_reliability_daily') }}
    group by line_id, calendar_date
),

snapshots_tagged as (
    select
        line_id,
        ingested_at,
        date_trunc('day', ingested_at at time zone 'UTC')::date as calendar_date,
        case when status_severity = 10 then 0 else 1 end as is_disrupted
    from {{ ref('stg_line_status') }}
),

run_ids as (
    -- Classic gaps-and-islands: rows that share both partition key and
    -- is_disrupted state share the same (rn1 - rn2) "run id".
    select
        line_id,
        calendar_date,
        is_disrupted,
        row_number() over (
            partition by line_id, calendar_date
            order by ingested_at
        )
        - row_number() over (
            partition by line_id, calendar_date, is_disrupted
            order by ingested_at
        ) as run_id
    from snapshots_tagged
),

run_lengths as (
    select line_id, calendar_date, run_id, count(*) as run_length
    from run_ids
    where is_disrupted = 1
    group by line_id, calendar_date, run_id
),

longest_runs as (
    select
        line_id,
        calendar_date,
        coalesce(max(run_length), 0) * 30.0 / 60.0
            as longest_disruption_window_minutes
    from run_lengths
    group by line_id, calendar_date
)

select
    r.line_id,
    r.line_name,
    r.mode,
    r.calendar_date,
    r.total_snapshots,
    r.good_service_snapshots,
    case
        when r.total_snapshots = 0 then null
        else round(
            r.good_service_snapshots::numeric / r.total_snapshots,
            4
        )
    end as pct_good_service,
    r.minutes_observed_estimate,
    coalesce(lr.longest_disruption_window_minutes, 0)
        as longest_disruption_window_minutes
from daily_rollup r
left join longest_runs lr
    on lr.line_id = r.line_id
   and lr.calendar_date = r.calendar_date
```

### Phase 3.5 — `mart_disruptions_daily.sql`

**File**: `dbt/models/marts/mart_disruptions_daily.sql` (new)

Fans out via `affected_routes`. Counts distinct disruptions per
(day, line). Uses `ingested_at` for the calendar bucket (same
rationale as the line-status mart: producer-stamped, monotonic).

```sql
with disruptions as (
    select
        ingested_at,
        date_trunc('day', ingested_at at time zone 'UTC')::date as calendar_date,
        disruption_id,
        category,
        severity,
        affected_routes
    from {{ ref('stg_disruptions') }}
),

fanned_out as (
    select
        d.calendar_date,
        d.ingested_at,
        d.disruption_id,
        d.category,
        d.severity,
        line_id
    from disruptions d
    cross join lateral jsonb_array_elements_text(d.affected_routes) as line_id
)

select
    calendar_date,
    line_id,
    count(distinct disruption_id) as disruption_count,
    array_agg(distinct category order by category) as distinct_categories,
    max(severity) as max_severity,
    min(ingested_at) as first_seen_at,
    max(ingested_at) as last_seen_at
from fanned_out
group by calendar_date, line_id
```

### Phase 3.6 — `mart_bus_metrics_daily.sql`

**File**: `dbt/models/marts/mart_bus_metrics_daily.sql` (new)

```sql
with bus_lines as (
    select line_id
    from {{ source('tfl', 'lines') }}
    where mode = 'bus'
),

predictions as (
    select
        a.line_id,
        a.station_id,
        a.expected_arrival,
        a.time_to_station_seconds,
        a.vehicle_id,
        a.ingested_at,
        date_trunc('day', a.ingested_at at time zone 'UTC')::date as calendar_date
    from {{ ref('stg_arrivals') }} a
    inner join bus_lines b on b.line_id = a.line_id
)

select
    calendar_date,
    line_id,
    station_id,
    count(*) as prediction_count,
    count(distinct vehicle_id)
        filter (where vehicle_id is not null)              as distinct_vehicles,
    avg(time_to_station_seconds)::numeric(12, 2)            as avg_time_to_station_seconds,
    min(time_to_station_seconds)                            as min_time_to_station_seconds,
    max(time_to_station_seconds)                            as max_time_to_station_seconds,
    min(expected_arrival)                                   as first_predicted_arrival,
    max(expected_arrival)                                   as last_predicted_arrival
from predictions
group by calendar_date, line_id, station_id
```

### Phase 3.7 — Mart schema docs + generic tests

Extend `dbt/models/marts/schema.yml` with three new `models:` blocks:

- `mart_tube_reliability_daily_summary` — `not_null` on the grain
  cols + `total_snapshots` + `minutes_observed_estimate` +
  `longest_disruption_window_minutes`. `pct_good_service` is
  nullable when `total_snapshots = 0` (documented).
- `mart_disruptions_daily` — `not_null` on `calendar_date`, `line_id`,
  `disruption_count`, `max_severity`, `first_seen_at`,
  `last_seen_at`.
- `mart_bus_metrics_daily` — `not_null` on grain cols +
  `prediction_count`.

### Phase 3.8 — Custom tests

Five new files under `dbt/tests/`:

- `assert_pct_good_service_bounded.sql`:
  ```sql
  select line_id, calendar_date, pct_good_service
  from {{ ref('mart_tube_reliability_daily_summary') }}
  where pct_good_service is not null
    and (pct_good_service < 0 or pct_good_service > 1)
  ```
- `assert_mart_tube_reliability_daily_summary_grain.sql` — composite
  uniqueness on `(line_id, calendar_date)`.
- `assert_mart_disruptions_daily_grain.sql` — composite uniqueness on
  `(calendar_date, line_id)`.
- `assert_mart_bus_metrics_daily_grain.sql` — composite uniqueness on
  `(calendar_date, line_id, station_id)`.
- `assert_disruption_category_known.sql` — fails when
  `stg_disruptions.category` is outside the
  `{RealTime, PlannedWork, Information, Incident, Undefined}` enum.

### Phase 3.9 — Exposures

**File**: `dbt/models/exposures.yml` (new)

```yaml
version: 2

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

  - name: api_status_history
    type: application
    url: https://tfl-monitor-api.example/api/v1/status/history
    description: "Line-status timeseries window."
    depends_on:
      - ref('mart_tube_reliability_daily')
    owner: { name: tfl-monitor-api, email: ops@tfl-monitor.invalid }

  - name: api_line_reliability
    type: application
    url: https://tfl-monitor-api.example/api/v1/reliability/{line_id}
    description: "Per-line daily reliability summary + drilldown."
    depends_on:
      - ref('mart_tube_reliability_daily_summary')
      - ref('mart_tube_reliability_daily')
    owner: { name: tfl-monitor-api, email: ops@tfl-monitor.invalid }

  - name: api_recent_disruptions
    type: application
    url: https://tfl-monitor-api.example/api/v1/disruptions/recent
    description: "Recent disruptions feed."
    depends_on:
      - ref('mart_disruptions_daily')
    owner: { name: tfl-monitor-api, email: ops@tfl-monitor.invalid }

  - name: api_bus_punctuality
    type: application
    url: https://tfl-monitor-api.example/api/v1/bus/{stop_id}/punctuality
    description: "Per-stop bus prediction freshness building blocks."
    depends_on:
      - ref('mart_bus_metrics_daily')
    owner: { name: tfl-monitor-api, email: ops@tfl-monitor.invalid }
```

### Phase 3.10 — Validation gate

Run, in order:

```bash
uv run task dbt-parse                                      # CI gate
uv run task lint                                           # Ruff + mypy
uv run task test                                           # pytest
make check                                                 # full chain
# Optional (requires `make up`):
uv run dbt build --project-dir dbt --profiles-dir dbt --target dev
```

Stop and report if any step fails.

### Phase 3.11 — PROGRESS.md + napkin

- Flip the TM-C3 row in `PROGRESS.md` to `✅ <date>` with a one-line
  note.
- Add a fresh entry under napkin §"Domain Behavior Guardrails" (or
  §"Execution & Validation"):
  > **[date] Resolve PR threads only where a fix was applied.**
  > For rejected threads, post the rationale reply but leave them
  > open — the human reviewer (the author) decides. Override only on
  > explicit team-lead green-light, e.g. to unblock a
  > `required_review_thread_resolution: true` policy.

### Phase 3.12 — PR

Open PR `feature/TM-C3-remaining-marts` → `main`.

PR body sections:

- **Summary** — three new marts + five exposures + two staging
  models.
- **Models** — file paths + grains + materialisations.
- **Tests** — generic + five singular tests; `dbt_utils` deliberately
  not added (same call as TM-C2).
- **TM-B4 dependency** — disruption + bus marts compile to empty
  tables until B4 lands populated raw rows; staging unnests and
  marts are written against the frozen Pydantic contracts so no
  re-work is needed afterwards.
- **Validation** — `dbt-parse`, `make check`, optional `dbt build`.
- **Closes TM-10**.

## Success criteria

- [ ] Two new staging models (`stg_arrivals`, `stg_disruptions`)
  exist + parse + carry generic tests in `dbt/models/staging/schema.yml`.
- [ ] Three new marts
  (`mart_tube_reliability_daily_summary`, `mart_disruptions_daily`,
  `mart_bus_metrics_daily`) exist + parse + carry generic tests in
  `dbt/models/marts/schema.yml`.
- [ ] Five custom singular tests under `dbt/tests/`.
- [ ] `dbt/models/exposures.yml` declares five exposures.
- [ ] `uv run task dbt-parse` exits 0 (only the pre-existing
  `intermediate` unused-config warning, which disappears once we
  populate that path or remove the empty config).
- [ ] `make check` exits 0.
- [ ] `uv run dbt build --target dev` exits 0 against local Compose
  Postgres (or PR body documents the manual command).
- [ ] PROGRESS.md TM-C3 row reads `✅ <date>` with a one-line note.
- [ ] napkin updated with the thread-resolution rule.
- [ ] PR opened with `Closes TM-10` in the body.
