---
hide:
  - navigation
  - toc
---

# tfl-monitor

> A real-time data + AI engineering portfolio: a **live Transport for London
> proxy** with a LangGraph agent that routes between live TfL queries and RAG
> over TfL strategy documents.

<div class="grid cards" markdown>

-   :material-train-variant:{ .lg .middle } **Live operational data**

    ---

    `/status/live` and `/disruptions/recent` read through to the TfL Unified
    API on demand — no broker, no feed warehouse to keep fresh (ADR 014).

    [:octicons-arrow-right-24: Live TfL proxy](pipelines/ingestion.md)

-   :material-database-outline:{ .lg .middle } **Reference data in dbt**

    ---

    One station seed and a `dim_stations` mart, built one-shot on deploy — with
    dbt tests, lineage, and docs for near-zero cost.

    [:octicons-arrow-right-24: Reference data](pipelines/warehouse.md)

-   :material-robot-outline:{ .lg .middle } **Agent that doesn't hallucinate**

    ---

    LangGraph routes between typed tools — live status, disruptions, journey,
    arrivals, and RAG. Every step traced in LangSmith.

    [:octicons-arrow-right-24: LangGraph agent](pipelines/agent.md)

-   :material-chart-line:{ .lg .middle } **Production-ready observability**

    ---

    LangSmith for LLM/agent decisions, Logfire for FastAPI / Postgres / HTTP.
    Zero self-hosted telemetry to babysit.

    [:octicons-arrow-right-24: Observability](observability.md)

-   :material-cloud-outline:{ .lg .middle } **Runs for a few $/month**

    ---

    A second tenant on a shared AWS Lightsail box + AWS Bedrock + free-tier
    Supabase / Vercel. Effective cost ~$3.50/mo.

    [:octicons-arrow-right-24: Deployment](deployment.md)

-   :material-format-list-checks:{ .lg .middle } **Built in tracked WPs**

    ---

    Work packages organised into parallel tracks; every WP shipped with tests,
    ADRs for cross-cutting decisions, contracts-first parallelism.

    [:octicons-arrow-right-24: Roadmap](roadmap.md)

</div>

## What you can ask the agent

```text
"How's the Piccadilly line running right now?"
   → query_tube_status → live TfL /Line/Mode/{modes}/Status

"Plan a journey from Oxford Circus to Bank."
   → plan_journey_tool → live TfL /Journey/JourneyResults

"What's TfL's strategy for cycling?"
   → search_tfl_docs → pgvector over TfL Business Plan + MTS 2018 +
     Annual Report (PyMuPDF-parsed, Bedrock-embedded)
```

## Why this exists

A portfolio that demonstrates the full data + AI engineering loop on a
realistic public dataset, not a CRUD demo or a notebook prototype:

- **A live proxy that knows what not to store.** The warehouse was decommissioned
  after it bricked the free-tier database three times; serving TfL live removed
  the disk-full failure class entirely (ADR 014).
- **A reference layer modelled properly.** dbt builds the station dimension with
  tests, lineage, and documentation, regenerable from empty in one `dbt build`.
- **An agent grounded in real data and real documents.** Typed,
  Pydantic-validated tools hit the live TfL API; RAG retrieval cites exact PDF
  chunks.
- **Everything traced.** LangSmith answers "why did the agent decide X?";
  Logfire answers "which TfL endpoint is throttling us?".

## Tech stack at a glance

| Layer | Choice |
|-------|--------|
| Streaming broker | None — live TfL proxy (ADR 014) |
| Database | PostgreSQL 16 / Supabase (app-essentials + pgvector) |
| Transformations | dbt-core (seed + `dim_stations`) |
| Orchestration | Host one-shot on deploy |
| Ingestion | Python 3.12 + `httpx` (read-through) |
| API | FastAPI + `sse-starlette` |
| Agent | LangGraph 1.x + Pydantic AI |
| RAG | LlamaIndex + pgvector + PyMuPDF + Bedrock Titan |
| Frontend | Next.js 16 + shadcn/ui + Biome |
| LLM observability | LangSmith |
| App observability | Logfire |
| Deploy | Shared AWS Lightsail + Bedrock + Supabase + Vercel |

[:octicons-arrow-right-24: Full tech-stack table](stack.md){ .md-button }
[:octicons-arrow-right-24: Architecture deep-dive](architecture.md){ .md-button .md-button--primary }

## About the author

Built by **[Humberto Slomeu](https://github.com/hcslomeu)** — AI engineer
available for hire.

[:fontawesome-brands-github: GitHub](https://github.com/hcslomeu) ·
[:fontawesome-brands-linkedin: LinkedIn](https://www.linkedin.com/in/hcslomeu/) ·
[:material-source-repository: Source code](https://github.com/hcslomeu/tfl-monitor)
