-- Composite-grain uniqueness on (calendar_date, line_id).

select calendar_date, line_id, count(*) as row_count
from {{ ref('mart_disruptions_daily') }}
group by calendar_date, line_id
having count(*) > 1
