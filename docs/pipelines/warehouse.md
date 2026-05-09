# dbt warehouse

Three Postgres schemas, ten dbt models, generic + singular tests, and five
exposures wiring marts to the API endpoints that consume them.

## Schema layout

| Schema | Purpose | Owned by |
|--------|---------|----------|
| `raw.*` | Append-only JSONB landing tables | Consumers (`src/ingestion/consumers/`) |
| `ref.*` | Reference data (lines, stations, modes) | TM-A2 static-ingest DAG (deferred) |
| `analytics.*` | dbt-built staging + marts | dbt project under `dbt/models/` |

## Lineage

```mermaid
flowchart TB
    subgraph RAW[raw schema]
      r1[(raw.line_status)]
      r2[(raw.arrivals)]
      r3[(raw.disruptions)]
    end

    subgraph STG[staging]
      s1[stg_line_status]
      s2[stg_arrivals]
      s3[stg_disruptions]
    end

    subgraph MART[marts]
      m1[mart_tube_reliability_daily]
      m2[mart_tube_reliability_daily_summary]
      m3[mart_disruptions_daily]
      m4[mart_bus_metrics_daily]
    end

    subgraph EXP[exposures]
      e1[/status/live, /status/history]
      e2[/reliability/{line_id}]
      e3[/disruptions/recent]
      e4[/bus/{stop_id}/punctuality]
    end

    r1 --> s1 --> m1 --> m2
    r2 --> s2 --> m4
    r3 --> s3 --> m3

    s1 --> e1
    m2 --> e2
    s3 --> e3
    s2 --> e4
```

## Staging models

All three staging models share the same shape:

- **Materialisation:** `incremental` with `unique_key='event_id'`, `merge`
  strategy, `on_schema_change='fail'`.
- **Lookback:** 5 minutes — incremental runs scan the last 5 min of `raw` rows
  in case a late event arrives.
- **Defensive dedup:** `row_number() OVER (PARTITION BY event_id ORDER BY
  ingested_at DESC)` then keep `rn = 1`.
- **JSONB unnesting:** explicit casts into typed columns (text / int /
  numeric / timestamptz). No silent JSONB leakage downstream.

Reading the staging models is the cheapest way to understand the wire format
of each topic.

## Marts

| Model | Grain | Notable columns |
|-------|-------|-----------------|
| `mart_tube_reliability_daily` | `(line_id, calendar_date_utc, status_severity)` | `snapshot_count`, `first_observed_at`, `last_observed_at`, `minutes_observed_estimate` |
| `mart_tube_reliability_daily_summary` | `(line_id, calendar_date_utc)` | `pct_good_service`, `longest_disruption_window_minutes` (gaps-and-islands) |
| `mart_disruptions_daily` | `(calendar_date_utc, line_id)` | `affected_routes` JSONB fan-out, `distinct_categories`, `max_severity` |
| `mart_bus_metrics_daily` | `(calendar_date_utc, line_id, station_id)` | Filtered to bus lines via `source('tfl', 'lines')` |

The `mart_tube_reliability_daily_summary` model is the most interesting — it
runs a gaps-and-islands SQL pattern to compute the longest contiguous
non-`Good Service` window per line per day:

```sql
with islands as (
    select
        line_id,
        calendar_date_utc,
        last_observed_at,
        sum(case when status_severity = 'Good Service' then 1 else 0 end)
            over (partition by line_id, calendar_date_utc order by last_observed_at) as island_id
    from {{ ref('mart_tube_reliability_daily') }}
)
select
    line_id,
    calendar_date_utc,
    max(extract(epoch from (last_observed_at - first_observed_at)) / 60.0)
        as longest_disruption_window_minutes
from (
    select
        line_id,
        calendar_date_utc,
        island_id,
        min(last_observed_at) as first_observed_at,
        max(last_observed_at) as last_observed_at
    from islands
    where status_severity != 'Good Service'
    group by 1, 2, 3
) windows
group by 1, 2
```

## Tests

| Type | Count | Examples |
|------|-------|----------|
| Generic (`unique`, `not_null`, `accepted_values`, relationships) | 14 | `event_id` is unique on every staging model |
| Singular | 8 | `pct_good_service` is bounded `[0, 100]`; `affected_routes` is valid JSONB; disruption category enum |

Singular tests live under `dbt/tests/` and run via `dbt test`. CI gates the
parser via `uv run task dbt-parse` on every PR.

## Exposures

Five exposures wire marts to the FastAPI endpoints that consume them, so
`dbt docs generate` produces a useful lineage graph for a recruiter:

```yaml
- name: api_status_live
  type: application
  url: https://tflmonitor.duckdns.org/api/v1/status/live
  depends_on: [source('tfl', 'line_status')]

- name: api_reliability_window
  type: application
  url: https://tflmonitor.duckdns.org/api/v1/reliability/{line_id}
  depends_on: [ref('mart_tube_reliability_daily')]
```

Five total — one per warehouse-backed endpoint.

## Idempotency and lateness

Three properties combine to make every mart re-runnable from scratch:

1. **`merge` materialisation** with `unique_key='event_id'` — re-running a
   batch updates rows in place rather than appending duplicates.
2. **5-minute lookback** — staging models scan the last 5 min of `raw` rows
   to catch late arrivals.
3. **UTC anchoring** — every `calendar_date_utc` derives from `ingested_at` in
   UTC, so re-running across timezones yields identical rows.

A nightly `dbt build` (`0 1 * * *` in `airflow/dags/dbt_nightly.py`)
rebuilds the marts from staging.
