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
