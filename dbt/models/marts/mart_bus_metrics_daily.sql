-- Daily bus-arrival prediction KPIs per (calendar_date UTC, line_id,
-- station_id). Bus lines only — joined against ref.lines on mode.
--
-- TfL does not publish actual departure events, so this mart surfaces
-- the prediction-side building blocks (counts, time-to-station
-- distribution, distinct vehicles). A true punctuality KPI lives in
-- the API layer (predicted vs actual freshness proxy).
--
-- While ref.lines is empty (until TM-A2 lands the static-ingest DAG),
-- the inner join returns zero rows. dbt-build remains green; once
-- ref.lines populates, the same SQL produces real KPIs.

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
        date_trunc('day', a.ingested_at at time zone 'UTC')::date       as calendar_date
    from {{ ref('stg_arrivals') }} a
    inner join bus_lines b on b.line_id = a.line_id
)

select
    calendar_date,
    line_id,
    station_id,
    count(*)                                                            as prediction_count,
    count(distinct vehicle_id) filter (where vehicle_id is not null)    as distinct_vehicles,
    avg(time_to_station_seconds)::numeric(12, 2)                        as avg_time_to_station_seconds,
    min(time_to_station_seconds)                                        as min_time_to_station_seconds,
    max(time_to_station_seconds)                                        as max_time_to_station_seconds,
    min(expected_arrival)                                               as first_predicted_arrival,
    max(expected_arrival)                                               as last_predicted_arrival
from predictions
group by calendar_date, line_id, station_id
