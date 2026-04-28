-- TfL severity codes are bounded 0..20; surface any drift so the
-- contract change can be reviewed.

select event_id, status_severity
from {{ ref('stg_line_status') }}
where status_severity not between 0 and 20
