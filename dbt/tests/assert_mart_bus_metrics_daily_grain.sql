-- Composite-grain uniqueness on (calendar_date, line_id, station_id).

select calendar_date, line_id, station_id, count(*) as row_count
from {{ ref('mart_bus_metrics_daily') }}
group by calendar_date, line_id, station_id
having count(*) > 1
