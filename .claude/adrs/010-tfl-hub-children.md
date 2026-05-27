# 010 — `TflStopPoint` carries hub children for forward resolution

Status: accepted
Date: 2026-05-27

## Context

TM-30 shipped a forward resolver (`stations.resolve_name`) that maps a
free-text station name to a StopPoint id via TfL `/StopPoint/Search`. A
prod smoke exposed a defect: for major interchanges (Bank, King's Cross,
Paddington, Victoria, …) the top Search match is a **hub** id
(`HUB*`, e.g. `HUBBAN`), and a hub id is **not** a usable endpoint:

- `/Journey/JourneyResults/.../to/HUBBAN` returns **HTTP 300** (TfL falls
  back to fuzzy text matching — `HUBBAN` matched "HUBBARD DRIVE" in
  Kingston), which propagated as an uncaught `TflClientError` and crashed
  the whole chat stream.
- `/StopPoint/HUBBAN/Arrivals` returns **0 predictions**.

The concrete child NaPTAN (e.g. `940GZZLUBNK`, Bank Underground) works for
both endpoints. A hub's `/StopPoint/{id}` payload lists those children
with their transport `modes`, so the resolver can dereference a hub to a
concrete rail platform — but `TflStopPoint` did not model `children`.

## Decision

Extend the tier-1 contract in `contracts/schemas/tfl_api.py`:

- Add `TflStopPointChild { naptan_id: str, modes: list[str] = [] }`.
- Add `children: list[TflStopPointChild] = []` to `TflStopPoint`
  (additive, default-empty, reusing `_tfl_model_config()`).

`resolve_name` dereferences a hub top-match by fetching `/StopPoint/{hub}`
and picking the highest-priority rail child by mode
(`tube > elizabeth-line > dlr > overground > national-rail`), falling back
to the hub id when no rail child is found. The journey/arrivals agent
tools additionally wrap their TfL calls so an uncaught upstream error can
never again crash the LangGraph stream (LangGraph's
`_default_handle_tool_errors` re-raises non-`ToolException` errors).

## Consequences

- **Additive only.** Existing consumers (the reverse `resolve_naptans`
  fallback reads only `common_name`) are unaffected; `children` defaults
  to empty. No tier-2 Kafka, OpenAPI, SQL, or dbt-source change → the CI
  source-mirror diff gate is untouched.
- One extra `/StopPoint/{hub}` call per *uncached* hub-name resolution;
  the existing `_NAME_CACHE` absorbs repeats, and non-hub names take no
  extra call.
- Child selection is a deterministic mode-priority heuristic, not an LLM
  call — cheaper and not prone to NaPTAN hallucination. Revisit if a hub
  ever lacks a rail child that callers expect (then the resolver returns
  the hub id and the tool degrades with a friendly message).
