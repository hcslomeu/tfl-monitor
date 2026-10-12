# Glossary

Project-specific vocabulary and TfL-specific terms a reviewer might not know.

## Project terms

`WP`
:   Work Package — the unit of work in this project. Identified `TM-XXX` (e.g.
    `TM-A5`). Each WP owns a directory track and ships in one PR. Specs live
    under `.claude/specs/TM-XXX-{spec,research,plan}.md`.

`Track`
:   A directory boundary. **A** infra, **B** ingestion, **D** api-agent,
    **E** frontend, **F** polish (track **C**, dbt, ended with ADR 015). At
    most two agents work concurrently on different tracks.

`Tier-1 schema`
:   Pydantic model mirroring the **raw TfL Unified API** payload — camelCase,
    optional-heavy. Lives in `contracts/schemas/tfl_api.py`. Ingestion parses
    these on the wire.

`Tier-2 schema`
:   Pydantic model in the **internal response shape** — snake_case, flat, typed.
    Lives in `contracts/schemas/`. `tfl_client/normalise.py` maps tier-1 →
    tier-2; FastAPI and the frontend speak only this.

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
    and stations. The `get_arrivals_tool` resolves a station name to a NaPTAN
    before querying live arrivals.

`ATCO`
:   Association of Transport Coordinating Officers. ATCO codes are the
    granular bus-stop identifier used in TfL bus arrivals.

`Line ID`
:   TfL's slug for a transit line, e.g. `piccadilly`, `elizabeth`,
    `bakerloo`. Returned as `line_id` by `/status/live` and
    `/disruptions/recent`.

`Mode`
:   TfL's transport-mode classifier — `tube`, `bus`, `dlr`, `overground`,
    `elizabeth-line`, `tram`, `cable-car`. `/status/live` and
    `/disruptions/recent` query TfL across the rail modes.

`Status severity`
:   TfL's enum: `Good Service`, `Minor Delays`, `Severe Delays`, `Part Closure`,
    `Suspended`, etc. Returned per line by `/status/live`; severity 10 is Good
    Service, higher values map to delays / closures.

## Stack terms

`Logfire span`
:   An OpenTelemetry span emitted by Logfire. One per FastAPI request
    (auto-instrumented) and one per outbound TfL call (`tfl.request`).

`LangSmith trace`
:   A LangChain-native trace covering an entire `/chat/stream` invocation —
    every node, tool call, and LLM call inside the LangGraph run.

`SSE` (Server-Sent Events)
:   The streaming protocol used by `/chat/stream`. Frames are
    `data: {…}\n\n`-terminated JSON. The Vercel function allows up to
    300 seconds (`maxDuration`) for a stream.

`create_react_agent`
:   LangGraph's prebuilt ReAct loop — model picks tools, runs them, feeds the
    output back to the model, terminates on a final assistant message.

`InMemorySaver`
:   LangGraph's in-process checkpointer. Holds chat memory per `thread_id`
    for the life of one function instance; nothing is persisted.

`Fluid compute`
:   Vercel's function runtime mode that reuses warm instances across
    concurrent requests. The API runs on it in region `lhr1`.

`s-maxage`
:   The `Cache-Control` directive that tells the Vercel CDN how long to serve
    a cached response. The live GET endpoints set `s-maxage=30`.
