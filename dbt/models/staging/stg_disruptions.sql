-- Cleansing layer over raw.disruptions. Unnests the JSONB payload into
-- typed columns; defensive dedup on event_id (the upstream PK already
-- enforces uniqueness, but staging is the right boundary to absorb any
-- future re-ingestion path).
--
-- affected_routes and affected_stops stay as JSONB arrays so the
-- downstream mart can fan out per impacted line / stop.

{{
    config(
        materialized='incremental',
        unique_key='event_id',
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

with source as (
    select
        event_id,
        ingested_at,
        event_type,
        source,
        payload
    from {{ source('tfl', 'disruptions') }}
    where event_type = 'disruptions.snapshot'
    {% if is_incremental() %}
      -- 5-minute lookback absorbs late-arriving events; merge on
      -- event_id makes the reprocessing safe.
      and ingested_at >= coalesce(
          (select max(ingested_at) - interval '5 minutes' from {{ this }}),
          '-infinity'::timestamptz
      )
    {% endif %}
),

deduped as (
    -- "Latest wins" if a future re-ingestion path ever produces two
    -- rows for the same event_id.
    select
        *,
        row_number() over (
            partition by event_id
            order by ingested_at desc
        ) as _rn
    from source
)

select
    event_id,
    ingested_at,
    event_type,
    source,
    (payload ->> 'disruption_id')::text                                as disruption_id,
    (payload ->> 'category')::text                                     as category,
    (payload ->> 'category_description')::text                         as category_description,
    (payload ->> 'description')::text                                  as description,
    (payload ->> 'summary')::text                                      as summary,
    nullif(payload ->> 'closure_text', '')::text                       as closure_text,
    (payload ->> 'severity')::int                                      as severity,
    (payload ->> 'created')::timestamptz                               as created,
    (payload ->> 'last_update')::timestamptz                           as last_update,
    payload -> 'affected_routes'                                       as affected_routes,
    payload -> 'affected_stops'                                        as affected_stops
from deduped
where _rn = 1
