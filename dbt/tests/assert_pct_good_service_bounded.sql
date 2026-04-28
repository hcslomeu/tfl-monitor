-- pct_good_service is a ratio: must be null (when total_snapshots = 0)
-- or strictly within [0, 1]. Anything outside that range indicates
-- a bug in the rollup arithmetic.

select line_id, calendar_date, pct_good_service, total_snapshots
from {{ ref('mart_tube_reliability_daily_summary') }}
where pct_good_service is not null
  and (pct_good_service < 0 or pct_good_service > 1)
