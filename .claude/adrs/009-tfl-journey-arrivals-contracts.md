# 009 — Tier-1 contracts for TfL journey planning and stop search

Status: accepted
Date: 2026-05-27

## Context

TM-30 (PR-C) adds two LangGraph agent tools — `plan_journey_tool` and
`get_arrivals_tool` — backed by two new `TflClient` methods that call TfL
endpoints the ingestion layer did not previously touch:

- `/Journey/JourneyResults/{from}/to/{to}` — multi-leg route planning.
- `/StopPoint/Search/{query}` — free-text name → StopPoint/NaPTAN id,
  used by the forward resolver `stations.resolve_name`.

The house rule is that every method on `TflClient` returns a parsed
tier-1 Pydantic model, never raw JSON (see `contracts/schemas/tfl_api.py`).
Both new endpoints return shapes with no existing model, so new tier-1
contracts are required. `AGENTS.md` requires any change under
`contracts/` to be formalised in an ADR — hence this record.

## Decision

Append six additive tier-1 models to `contracts/schemas/tfl_api.py`, all
reusing `_tfl_model_config()` (`alias_generator=to_camel`,
`populate_by_name=True`, `extra="ignore"`, `frozen=True`):

- `TflJourneyMode { name }` and `TflJourneyInstruction { summary }` —
  modelled as explicit sub-models because `to_camel` aliasing does not
  reach into nested objects.
- `TflJourneyLeg { duration, mode, instruction, departure_time?,
  arrival_time? }`.
- `TflJourneyResult { start_date_time, arrival_date_time, duration,
  legs[] }` — one entry of the response `journeys[]` array.
- `TflStopSearchMatch { id, name, modes[] }` and
  `TflStopSearchResponse { matches[] }`; `id` is the StopPoint/NaPTAN.

These are **tier-1 ingestion DTOs** (raw TfL wire shapes), not the tier-2
Kafka event schemas and not the public OpenAPI surface. No
`contracts/openapi.yaml`, `contracts/sql/`, or `contracts/dbt_sources.yml`
file is touched, so the CI source-mirror diff gate is unaffected and no
`web/lib/types.ts` regeneration is needed.

## Consequences

- **Additive only.** No existing model changes; nothing downstream breaks.
  `extra="ignore"` discards the ~20 noise fields TfL ships per record.
- **No public API change.** Journey and arrivals are agent-internal tools,
  not new REST endpoints — there is no OpenAPI drift and no frontend type
  change. Rich `<JourneyCard>` rendering (which would add a structured SSE
  frame to the public surface) is deliberately deferred to a follow-up WP.
- **Future journey consumers** (e.g. a journey SSE frame, or a REST
  `/journey` endpoint) must reuse this envelope or revisit this ADR if a
  second shape variant is needed.
