-- Cleansing layer over raw.line_status. Unnests the JSONB payload into
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
    from {{ source('tfl', 'line_status') }}
    {% if is_incremental() %}
    where ingested_at > coalesce(
        (select max(ingested_at) from {{ this }}),
        '-infinity'::timestamptz
    )
    {% endif %}
),

deduped as (
    select
        *,
        row_number() over (
            partition by event_id
            order by ingested_at
        ) as _rn
    from source
)

select
    event_id,
    ingested_at,
    event_type,
    source,
    (payload ->> 'line_id')::text                                      as line_id,
    (payload ->> 'line_name')::text                                    as line_name,
    (payload ->> 'mode')::text                                         as mode,
    (payload ->> 'status_severity')::int                               as status_severity,
    (payload ->> 'status_severity_description')::text                  as status_severity_description,
    nullif(payload ->> 'reason', '')::text                             as reason,
    (payload ->> 'valid_from')::timestamptz                            as valid_from,
    (payload ->> 'valid_to')::timestamptz                              as valid_to
from deduped
where _rn = 1
  and event_type = 'line-status.snapshot'
