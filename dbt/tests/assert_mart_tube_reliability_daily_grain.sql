-- The mart promises one row per (line_id, calendar_date,
-- status_severity). Singular test in lieu of pulling in dbt_utils.

select line_id, calendar_date, status_severity, count(*) as row_count
from {{ ref('mart_tube_reliability_daily') }}
group by line_id, calendar_date, status_severity
having count(*) > 1
