-- Composite-grain uniqueness on (line_id, calendar_date). Singular
-- test in lieu of pulling in dbt_utils.

select line_id, calendar_date, count(*) as row_count
from {{ ref('mart_tube_reliability_daily_summary') }}
group by line_id, calendar_date
having count(*) > 1
