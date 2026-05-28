# Pipelines

Six end-to-end flows make up the system. Each page below walks the code path,
the contract that locks its boundaries, and the tests that protect it.

<div class="grid cards" markdown>

-   :material-source-branch:{ .lg .middle } **[Live TfL proxy](ingestion.md)**

    Async read-through to the TfL Unified API on demand → tier-2 Pydantic
    response. No broker, no feed warehouse (ADR 014).

-   :material-database-arrow-down:{ .lg .middle } **[Reference data (dbt)](warehouse.md)**

    A station seed and one `dim_stations` mart, built one-shot on deploy — the
    fast path for the NaPTAN → station-name resolver.

-   :material-file-document-multiple-outline:{ .lg .middle } **[RAG ingestion](rag.md)**

    Conditional GET on TfL strategy PDFs → PyMuPDF parse → Bedrock Titan
    embeddings → pgvector, keyed by `doc_id`.

-   :material-graph:{ .lg .middle } **[LangGraph agent](agent.md)**

    Up to five typed tools (live status, disruptions, journey, arrivals, RAG),
    a Pydantic AI extractor, and a structured SSE projection.

-   :material-api:{ .lg .middle } **[FastAPI surface](api.md)**

    Five endpoints, all RFC 7807 errors, a single async psycopg pool, and
    OpenAPI 3.1 as the contract.

-   :material-language-typescript:{ .lg .middle } **[Next.js frontend](frontend.md)**

    A one-pager dashboard + chat, all server components by default, types
    regenerated from OpenAPI.

</div>
