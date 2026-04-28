-- DisruptionCategory enum mirror. The schema.yml accepted_values test
-- already enforces this for stg_disruptions; this singular test
-- reinforces it project-wide and demonstrates how to keep an enum
-- bounded without forcing every consumer to re-read the Python
-- contract.

select event_id, category
from {{ ref('stg_disruptions') }}
where category not in (
    'RealTime',
    'PlannedWork',
    'Information',
    'Incident',
    'Undefined'
)
