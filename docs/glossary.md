# Glossary

Project-specific vocabulary and TfL-specific terms a reviewer might not know.

## Project terms

`WP`
:   Work Package — the unit of work in this project. Identified `TM-XXX` (e.g.
    `TM-A5`). Each WP owns a directory track and ships in one PR. Specs live
    under `.claude/specs/TM-XXX-{spec,research,plan}.md`.

`Track`
:   A directory boundary. **A** infra, **B** ingestion, **C** dbt,
    **D** api-agent, **E** frontend, **F** polish. At most two agents work
    concurrently on different tracks.

`Tier-1 schema`
:   Pydantic model mirroring the **raw TfL Unified API** payload — camelCase,
    optional-heavy. Lives in `contracts/schemas/tfl_api.py`. Ingestion parses
    these on the wire.

`Tier-2 schema`
:   Pydantic model in **internal Kafka wire format** — snake_case, frozen,
    flat. Lives in `contracts/schemas/{line_status,arrivals,disruptions}.py`.
    Producers emit these; consumers and downstream services speak only this.

`ADR`
:   Architecture Decision Record. Markdown file under `.claude/adrs/` with
    Context / Decision / Consequences. Required for every change under
    `contracts/` or any tech-stack substitution.

`Napkin`
:   A continuously curated runbook at `.claude/napkin.md` (not a session log)
    capturing recurring high-value guidance for future agents.

## TfL domain terms

`NaPTAN`
:   National Public Transport Access Node. The UK-wide identifier for stops
    and stations. Five NaPTAN hubs are sampled by the arrivals producer.

`ATCO`
:   Association of Transport Coordinating Officers. ATCO codes are the
    granular bus-stop identifier used in TfL bus arrivals.

`Line ID`
:   TfL's slug for a transit line — e.g. `piccadilly`, `elizabeth`,
    `bakerloo`. The `LineId` Pydantic AI normaliser converts free-text
    questions ("how's the Piccadilly?") into the canonical slug.

`Mode`
:   TfL's transport-mode classifier — `tube`, `bus`, `dlr`, `overground`,
    `elizabeth-line`, `tram`, `cable-car`. The disruptions producer polls
    four modes.

`Status severity`
:   TfL's enum: `Good Service`, `Minor Delays`, `Severe Delays`, `Part Closure`,
    `Suspended`, etc. `mart_tube_reliability_daily` aggregates per
    `(line_id, calendar_date, status_severity)`.

## Stack terms

`Logfire span`
:   An OpenTelemetry span emitted by Logfire's auto-instrumentation. One per
    request, query, or HTTP call.

`LangSmith trace`
:   A LangChain-native trace covering an entire `/chat/stream` invocation —
    every node, tool call, LLM call, and retrieval inside the LangGraph run.

`SSE` (Server-Sent Events)
:   The streaming protocol used by `/chat/stream`. Frames are
    `data: {…}\n\n`-terminated JSON. Caddy needs `flush_interval -1` to avoid
    buffering them.

`create_react_agent`
:   LangGraph's prebuilt ReAct loop — model picks tools, runs them, feeds the
    output back to the model, terminates on a final assistant message.

`Pydantic AI`
:   A typed Python agent framework from the Pydantic team; we use it inside one tool (`LineId`
    extraction with Haiku). LangGraph remains the main agent.

`HybridChunker`
:   Docling 2.x utility that chunks a parsed document by sections + tables
    rather than by raw character count, preserving semantic structure.
