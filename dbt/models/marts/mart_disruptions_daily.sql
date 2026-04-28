-- Daily disruption KPIs per (calendar_date UTC, line_id).
--
-- A single disruption can affect several lines (the affected_routes
-- payload field is a list). The model fans out via
-- jsonb_array_elements_text so a 3-line disruption counts on three
-- daily rows.
--
-- ingested_at is the calendar bucket: TM-B1's normaliser synthesises
-- payload.created and payload.last_update to "now()" when TfL omits
-- them, so they are not load-bearing for time-window KPIs. The
-- ingested_at column is producer-stamped and monotonic, mirroring
-- the convention set by mart_tube_reliability_daily.

with disruptions as (
    select
        ingested_at,
        date_trunc('day', ingested_at at time zone 'UTC')::date         as calendar_date,
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
    count(distinct disruption_id)                                       as disruption_count,
    array_agg(distinct category order by category)                      as distinct_categories,
    max(severity)                                                       as max_severity,
    min(ingested_at)                                                    as first_seen_at,
    max(ingested_at)                                                    as last_seen_at
from fanned_out
group by calendar_date, line_id
