# Pipelines

Six end-to-end flows make up the system. Each page below walks the code path,
the contract that locks its boundaries, and the tests that protect it.

<div class="grid cards" markdown>

-   :material-source-branch:{ .lg .middle } **[Streaming ingestion](ingestion.md)**

    Async TfL polling → tier-2 Pydantic events → Kafka topics → idempotent
    `raw.*` writes.

-   :material-database-arrow-down:{ .lg .middle } **[dbt warehouse](warehouse.md)**

    Staging models with defensive dedup, marts on stable composite grains,
    exposures that wire marts to API endpoints.

-   :material-file-document-multiple-outline:{ .lg .middle } **[RAG ingestion](rag.md)**

    Conditional GET on TfL strategy PDFs → Docling parse → OpenAI embeddings
    → Pinecone namespace per document.

-   :material-graph:{ .lg .middle } **[LangGraph agent](agent.md)**

    Five typed tools (4 SQL + 1 RAG), a Haiku normaliser for `LineId`, and a
    SSE projection for streaming.

-   :material-api:{ .lg .middle } **[FastAPI surface](api.md)**

    Six endpoints, all RFC 7807 errors, a single async psycopg pool, and
    OpenAPI 3.1 as the contract.

-   :material-language-typescript:{ .lg .middle } **[Next.js frontend](frontend.md)**

    Three views (Network Now, Disruption Log, Ask), all server components by
    default, types regenerated from OpenAPI.

</div>
