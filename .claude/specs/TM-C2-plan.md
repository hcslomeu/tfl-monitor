# TM-C2 — Implementation plan (Phase 2)

Source: `TM-C2-research.md`. Every Phase-2 recommendation is locked
in here as a **decision** unless a sub-phase note overrides it.

## Decisions

- **D1 — Mart materialization**: project default (`table`). No
  per-model override.
- **D2 — Producer cadence constant**: hard-code `30.0` seconds in the
  mart SQL with a comment pointing at
  `LINE_STATUS_POLL_PERIOD_SECONDS` in
  `src/ingestion/producers/line_status.py`.
- **D3 — Schema doc filenames**: `dbt/models/staging/schema.yml` and
  `dbt/models/marts/schema.yml` (matching the team-lead briefing).
- **D4 — No `dbt_utils`**: composite-grain uniqueness via a singular
  test under `dbt/tests/`.
- **D5 — Mart grain**: `(line_id, calendar_date, status_severity)`,
  per the briefing. KPIs at that grain only; daily summary deferred
  to TM-C3 / TM-D2.
- **D6 — `dbt build` smoke**: best-effort local run if Compose is up;
  otherwise skip and rely on `dbt-parse` + manual SQL review. CI gate
  is `dbt-parse`.
- **D7 — Calendar bucket**: `date_trunc('day', ingested_at AT TIME ZONE
  'UTC')::date AS calendar_date`. Documented in `schema.yml`.
- **D8 — Staging dedup idiom**: `row_number() OVER (PARTITION BY
  event_id ORDER BY ingested_at)` filtered to `rn = 1`. Defensive — the
  PK on `raw.line_status` already prevents duplicates.
- **D9 — Staging incremental strategy**: `merge` on `unique_key =
  'event_id'`, with an `is_incremental()` watermark on `ingested_at`.

## Summary

Add the first cleansing layer (`stg_line_status`) and the first mart
(`mart_tube_reliability_daily`) to the dbt project, with column docs,
generic and custom tests, and PR plumbing. No code outside `dbt/` is
touched. CI gate (`dbt-parse`) stays green; `dbt build` succeeds
against local Compose Postgres before the PR opens.

## Execution mode

- **Author of change:** single-track WP — execute serially in the main
  workspace.
- **Branch:** `feature/TM-C2-line-status-mart`.
- **PR title:** `feat(dbt): TM-C2 stg_line_status + mart_tube_reliability_daily (TM-9)`.
- **PR body:** `Closes TM-9`; lists deliverables, the grain decision,
  the cadence assumption baked into `minutes_observed_estimate`, and
  the reason `dbt_utils` was not added.

## What we're NOT doing

- Not editing `contracts/dbt_sources.yml` or `dbt/sources/tfl.yml`
  — frozen contract surface, mirrored under CI.
- Not adding `dbt_utils` (or any other dbt package). One ~10-line
  singular SQL test replaces what `unique_combination_of_columns`
  would do.
- Not touching `arrivals` or `disruptions` source tables. Those are
  unpopulated until TM-B4; staging + marts for them are TM-C3.
- Not building intermediate (`int_*`) models. The two-step
  source → staging → mart shape is enough at this scope.
- Not adding `dbt-build` or `dbt-test` to `taskipy` / `make check`.
  Both require a live Postgres; CI doesn't have a warehouse fixture
  for dbt yet (revisit in TM-A2 / TM-C3).
- Not adding a `mart_tube_reliability_daily_summary` (one grain above
  the WP's mart) — TM-C3.
- Not wiring the mart into `/reliability/{line_id}` — TM-D2.
- Not adding a longest-disruption-window KPI — fragile under uneven
  scrape cadence; TM-C3 will revisit alongside the disruption marts.
- Not changing the project-default materializations in
  `dbt_project.yml`. Staging stays `view`; marts stay `table`.
  An override on `stg_line_status` sets it to `incremental` in-model
  (per the team-lead briefing), without changing the staging default
  for future siblings (e.g. `stg_lines`, which should stay `view`).

## Sub-phases

### Phase 3.1 — Staging model

**File:** `dbt/models/staging/stg_line_status.sql` (new)

```sql
-- Cleansing layer over raw.line_status. Unnests the JSONB payload into
-- typed columns; defensive dedup on event_id (the upstream PK already
-- enforces uniqueness, but staging is the right boundary to absorb any
-- future re-ingestion path).

{{
    config(
        materialized='incremental',
        unique_key='event_id',
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

with source as (
    select
        event_id,
        ingested_at,
        event_type,
        source,
        payload
    from {{ source('tfl', 'line_status') }}
    {% if is_incremental() %}
    where ingested_at > coalesce(
        (select max(ingested_at) from {{ this }}),
        '-infinity'::timestamptz
    )
    {% endif %}
),

deduped as (
    select
        *,
        row_number() over (
            partition by event_id
            order by ingested_at
        ) as _rn
    from source
)

select
    event_id,
    ingested_at,
    event_type,
    source,
    (payload ->> 'line_id')::text                                      as line_id,
    (payload ->> 'line_name')::text                                    as line_name,
    (payload ->> 'mode')::text                                         as mode,
    (payload ->> 'status_severity')::int                               as status_severity,
    (payload ->> 'status_severity_description')::text                  as status_severity_description,
    nullif(payload ->> 'reason', '')::text                             as reason,
    (payload ->> 'valid_from')::timestamptz                            as valid_from,
    (payload ->> 'valid_to')::timestamptz                              as valid_to
from deduped
where _rn = 1
  and event_type = 'line-status.snapshot'
```

Notes:

- `on_schema_change='fail'` keeps the contract tight. Adding a new
  payload field requires an explicit dbt run + plan update.
- The defensive `event_type` filter mirrors the producer's literal.
  If a future producer ships a different event-type on the same
  topic, we want to find out at staging rather than at the mart.

### Phase 3.2 — Staging schema docs + tests

**File:** `dbt/models/staging/schema.yml` (new)

```yaml
version: 2

models:
  - name: stg_line_status
    description: |
      Cleansed line-status snapshots. One row per Kafka event; payload
      JSONB unnested into typed columns. Defensively deduplicated on
      event_id; sourced from raw.line_status (PK = event_id) so the
      dedup is a no-op in steady state.
    columns:
      - name: event_id
        description: "Unique event identifier (UUIDv4 from the producer)."
        tests:
          - not_null
          - unique
      - name: ingested_at
        description: "UTC timestamp stamped by the producer at fetch time."
        tests:
          - not_null
      - name: event_type
        description: "Discriminator literal — always 'line-status.snapshot'."
        tests:
          - not_null
          - accepted_values:
              values: ["line-status.snapshot"]
      - name: source
        description: "Origin of the event — always 'tfl-unified-api'."
        tests:
          - not_null
      - name: line_id
        description: "TfL line identifier (e.g. 'victoria')."
        tests:
          - not_null
      - name: line_name
        description: "Human-readable line name."
        tests:
          - not_null
      - name: mode
        description: "Transport mode (TransportMode enum string)."
        tests:
          - not_null
          - accepted_values:
              values:
                - tube
                - elizabeth-line
                - overground
                - dlr
                - bus
                - national-rail
                - river-bus
                - cable-car
                - tram
      - name: status_severity
        description: "TfL severity code 0..20 (10 = good service)."
        tests:
          - not_null
      - name: status_severity_description
        description: "Human-readable status (e.g. 'Good Service')."
        tests:
          - not_null
      - name: reason
        description: "Free-text disruption reason; null on healthy snapshots."
      - name: valid_from
        description: "UTC start of the status's validity window."
        tests:
          - not_null
      - name: valid_to
        description: "UTC end of the validity window; strictly greater than valid_from."
        tests:
          - not_null
```

The bounded `0..20` invariant on `status_severity` is enforced by the
custom test in Phase 3.4 rather than `accepted_values`, to demonstrate
the singular-test pattern (and to keep the YAML readable).

### Phase 3.3 — Mart model

**File:** `dbt/models/marts/mart_tube_reliability_daily.sql` (new)

```sql
-- First mart for line-status reliability KPIs. Grain:
--   (line_id, calendar_date UTC, status_severity).
-- One snapshot ≈ 30 s of wall-clock observation; this assumption is
-- baked into minutes_observed_estimate. Source of truth for the
-- cadence is LINE_STATUS_POLL_PERIOD_SECONDS in
-- src/ingestion/producers/line_status.py — keep them in sync.

with snapshots as (
    select
        line_id,
        line_name,
        mode,
        status_severity,
        status_severity_description,
        ingested_at,
        date_trunc('day', ingested_at at time zone 'UTC')::date as calendar_date
    from {{ ref('stg_line_status') }}
)

select
    line_id,
    min(line_name) as line_name,
    min(mode) as mode,
    calendar_date,
    status_severity,
    min(status_severity_description) as status_severity_description,
    count(*) as snapshot_count,
    min(ingested_at) as first_observed_at,
    max(ingested_at) as last_observed_at,
    -- 30 s producer cadence → 0.5 minutes per snapshot.
    (count(*) * 30.0 / 60.0)::numeric(12, 2) as minutes_observed_estimate
from snapshots
group by line_id, calendar_date, status_severity
```

`min(line_name)` / `min(mode)` are safe because the producer never
remaps a `line_id` to a different name or mode within a day. The
aggregate keeps the SQL pure-aggregation (no self-join, no `distinct
on`).

### Phase 3.4 — Mart schema docs + tests

**File:** `dbt/models/marts/schema.yml` (new)

```yaml
version: 2

models:
  - name: mart_tube_reliability_daily
    description: |
      Daily reliability KPIs per (line, calendar date UTC, status
      severity). One row counts how many line-status snapshots arrived
      for that triple, with first/last observation timestamps and a
      coverage estimate in minutes (one snapshot ≈ 30 s, mirroring
      LINE_STATUS_POLL_PERIOD_SECONDS).

      To compute the daily "% time in good service" per line, sum
      snapshot_count where status_severity = 10 and divide by the
      sum across all severities for that (line_id, calendar_date).
    columns:
      - name: line_id
        description: "TfL line identifier."
        tests:
          - not_null
      - name: line_name
        description: "Human-readable line name (denormalised from staging)."
        tests:
          - not_null
      - name: mode
        description: "Transport mode (TransportMode enum string)."
        tests:
          - not_null
      - name: calendar_date
        description: "UTC calendar date derived from ingested_at."
        tests:
          - not_null
      - name: status_severity
        description: "TfL severity code 0..20."
        tests:
          - not_null
      - name: status_severity_description
        description: "Human-readable status for the severity."
        tests:
          - not_null
      - name: snapshot_count
        description: "Count of line-status snapshots at this grain."
        tests:
          - not_null
      - name: first_observed_at
        description: "Earliest ingested_at seen for the triple."
        tests:
          - not_null
      - name: last_observed_at
        description: "Latest ingested_at seen for the triple."
        tests:
          - not_null
      - name: minutes_observed_estimate
        description: |
          Estimated wall-clock minutes covered by the snapshots in
          this row. Assumes a fixed 30 s producer cadence.
        tests:
          - not_null
```

### Phase 3.5 — Custom tests

**File:** `dbt/tests/assert_status_severity_known.sql` (new)

```sql
-- TfL severity codes are bounded 0..20; surface any drift so the
-- contract change can be reviewed.

select event_id, status_severity
from {{ ref('stg_line_status') }}
where status_severity not between 0 and 20
```

**File:** `dbt/tests/assert_mart_tube_reliability_daily_grain.sql` (new)

```sql
-- The mart promises one row per (line_id, calendar_date,
-- status_severity). Singular test in lieu of pulling in dbt_utils.

select line_id, calendar_date, status_severity, count(*) as row_count
from {{ ref('mart_tube_reliability_daily') }}
group by line_id, calendar_date, status_severity
having count(*) > 1
```

### Phase 3.6 — Validation gate

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

### Phase 3.7 — PROGRESS.md

Flip the TM-C2 row to `✅ <date>` with a one-line note pointing at the
mart grain and the `30.0 s` cadence assumption.

### Phase 3.8 — PR

Open PR `feature/TM-C2-line-status-mart` → `main`.

PR body sections:

- **Summary** — first staging + mart for the C-dbt track.
- **Models** — file names + grain + materialization.
- **Tests** — generic + two singular tests; explicit note that
  `dbt_utils` was deliberately not added.
- **KPI assumption** — `minutes_observed_estimate` baked on the 30 s
  producer cadence; cross-link to
  `LINE_STATUS_POLL_PERIOD_SECONDS`.
- **Validation** — `uv run task dbt-parse`, `make check`, optional
  `dbt build` against local Compose.
- **Closes TM-9**.

## Success criteria

- [ ] `dbt/models/staging/stg_line_status.sql` exists and parses.
- [ ] `dbt/models/staging/schema.yml` documents every column and ships
  generic tests on `event_id`, `ingested_at`, `line_id`, `mode`, etc.
- [ ] `dbt/models/marts/mart_tube_reliability_daily.sql` exists and
  parses.
- [ ] `dbt/models/marts/schema.yml` documents the grain + KPI columns.
- [ ] `dbt/tests/assert_status_severity_known.sql` and
  `dbt/tests/assert_mart_tube_reliability_daily_grain.sql` exist.
- [ ] `uv run task dbt-parse` exits 0.
- [ ] `make check` exits 0.
- [ ] `uv run dbt build --target dev` exits 0 against local Compose
  Postgres (or, if Compose is not up, the PR body documents the
  manual command).
- [ ] PROGRESS.md TM-C2 row reads `✅ <date>` with a one-line note.
- [ ] PR opened with `Closes TM-9` in the body.
- [ ] Linear TM-9 transitions to Done on merge (auto via integration).
