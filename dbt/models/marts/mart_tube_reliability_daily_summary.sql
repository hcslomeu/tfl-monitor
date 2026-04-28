-- One-grain-above rollup of mart_tube_reliability_daily.
-- Grain: (line_id, calendar_date UTC). One row per (line, day).
--
-- Ratios + counts come from mart_tube_reliability_daily (already
-- aggregated; lineage stays clean). longest_disruption_window_minutes
-- is a gaps-and-islands query against stg_line_status — it needs the
-- ordered raw observations the mart has lost.
--
-- See mart_tube_reliability_daily for the 30 s producer-cadence
-- assumption baked into minutes_observed_estimate.

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

disrupted_runs as (
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
    from disrupted_runs
    group by line_id, calendar_date
)

select
    r.line_id,
    r.line_name,
    r.mode,
    r.calendar_date,
    r.total_snapshots,
    coalesce(r.good_service_snapshots, 0)                              as good_service_snapshots,
    case
        when r.total_snapshots = 0 then null
        else round(
            coalesce(r.good_service_snapshots, 0)::numeric / r.total_snapshots,
            4
        )
    end                                                                as pct_good_service,
    r.minutes_observed_estimate,
    coalesce(lr.longest_disruption_window_minutes, 0)::numeric(12, 2)
        as longest_disruption_window_minutes
from daily_rollup r
left join longest_runs lr
    on lr.line_id = r.line_id
   and lr.calendar_date = r.calendar_date
