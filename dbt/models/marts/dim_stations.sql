{{
    config(
        materialized='table',
    )
}}

select
    naptan_id,
    name,
    line_ids,
    modes
from {{ ref('tfl_stations') }}
