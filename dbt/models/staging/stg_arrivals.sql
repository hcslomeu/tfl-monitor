-- Cleansing layer over raw.arrivals. Unnests the JSONB payload into
-- typed columns; defensive dedup on event_id (the upstream PK already
-- enforces uniqueness, but staging is the right boundary to absorb any
-- future re-ingestion path).

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
    from {{ source('tfl', 'arrivals') }}
    where event_type = 'arrivals.snapshot'
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
    (payload ->> 'arrival_id')::text                                   as arrival_id,
    (payload ->> 'station_id')::text                                   as station_id,
    (payload ->> 'station_name')::text                                 as station_name,
    (payload ->> 'line_id')::text                                      as line_id,
    (payload ->> 'platform_name')::text                                as platform_name,
    (payload ->> 'direction')::text                                    as direction,
    (payload ->> 'destination')::text                                  as destination,
    (payload ->> 'expected_arrival')::timestamptz                      as expected_arrival,
    (payload ->> 'time_to_station_seconds')::int                       as time_to_station_seconds,
    nullif(payload ->> 'vehicle_id', '')::text                         as vehicle_id
from deduped
where _rn = 1
