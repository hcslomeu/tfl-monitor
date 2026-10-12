# Pipelines

Four end-to-end flows make up the system. Each page below walks the code path,
the contract that locks its boundaries, and the tests that protect it.

<div class="grid cards" markdown>

-   :material-source-branch:{ .lg .middle } **[Live TfL proxy](ingestion.md)**

    Async read-through to the TfL Unified API on demand → tier-2 Pydantic
    response, cached 30 seconds at the CDN. No broker, no warehouse, no
    database (ADR 014, ADR 015).

-   :material-graph:{ .lg .middle } **[LangGraph agent](agent.md)**

    Four typed live TfL tools (status, disruptions, journey, arrivals), Claude
    via the Anthropic API, and a structured SSE projection.

-   :material-api:{ .lg .middle } **[FastAPI surface](api.md)**

    Four endpoints, RFC 7807 errors, a stateless Vercel function, and
    OpenAPI 3.1 as the contract.

-   :material-language-typescript:{ .lg .middle } **[Next.js frontend](frontend.md)**

    A one-pager dashboard + chat, all server components by default, types
    regenerated from OpenAPI.

</div>

The RAG ingestion pipeline and the dbt reference-data layer were removed in
ADR 015.
