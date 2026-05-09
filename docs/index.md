---
hide:
  - navigation
  - toc
---

# tfl-monitor

> A real-time data + AI engineering portfolio: streaming Transport for London
> feeds into a dbt-modelled warehouse, with a LangGraph agent that routes
> between SQL over the warehouse and RAG over TfL strategy documents.

<div class="grid cards" markdown>

-   :material-train-variant:{ .lg .middle } **Live operational data**

    ---

    Async pollers fan TfL line-status, arrivals, and disruptions onto Kafka
    topics every 30 s — replayable, decoupled from consumers.

    [:octicons-arrow-right-24: Streaming ingestion](pipelines/ingestion.md)

-   :material-database-outline:{ .lg .middle } **dbt-modelled warehouse**

    ---

    Staging + mart models with `merge` incrementality, generic + singular
    tests, and exposures wiring marts to API endpoints.

    [:octicons-arrow-right-24: dbt warehouse](pipelines/warehouse.md)

-   :material-robot-outline:{ .lg .middle } **Agent that doesn't hallucinate**

    ---

    LangGraph routes between five typed tools (4 SQL + 1 RAG). Pydantic AI
    extracts structured arguments. Every step traced in LangSmith.

    [:octicons-arrow-right-24: LangGraph agent](pipelines/agent.md)

-   :material-chart-line:{ .lg .middle } **Production-ready observability**

    ---

    LangSmith for LLM/agent decisions, Logfire for FastAPI / Postgres / HTTP.
    Zero self-hosted telemetry to babysit.

    [:octicons-arrow-right-24: Observability](observability.md)

-   :material-cloud-outline:{ .lg .middle } **Deployable for ~$6/month**

    ---

    Single EC2 spot box + AWS Bedrock + free-tier Supabase / Redpanda Cloud /
    Vercel / Pinecone. $100 AWS credit covers ~12 months.

    [:octicons-arrow-right-24: Deployment](deployment.md)

-   :material-format-list-checks:{ .lg .middle } **Built in tracked WPs**

    ---

    25 work packages organised into parallel tracks; every WP shipped with
    tests, ADRs for cross-cutting decisions, contracts-first parallelism.

    [:octicons-arrow-right-24: Roadmap](roadmap.md)

</div>

## What you can ask the agent

```text
"Which Tube line had the worst reliability last week?"
   → routes to SQL tool → mart_tube_reliability_daily_summary

"What's TfL's strategy for Piccadilly Line upgrades?"
   → routes to RAG tool → Pinecone over TfL Business Plan + MTS 2018 +
     Annual Report (Docling-parsed)

"Is the 207 bus running on time near Ealing Hospital?"
   → SQL → bus punctuality proxy from arrivals topic
```

## Why this exists

A portfolio that demonstrates the full data + AI engineering loop on a
realistic public dataset, not a CRUD demo or a notebook prototype:

- **Streaming that earns its broker.** Four polling endpoints with sub-minute
  cadence, multiple consumers fanning out from the same topic.
- **A warehouse modelled properly.** dbt staging → marts with tests, exposures,
  documentation, and idempotent `merge` incrementality.
- **An agent grounded in real data and real documents.** SQL tools run typed
  Pydantic-validated queries; RAG retrieval cites exact PDF chunks.
- **Everything traced.** LangSmith answers "why did the agent decide X?";
  Logfire answers "why is the consumer lagging?".

## Tech stack at a glance

| Layer | Choice |
|-------|--------|
| Streaming broker | Redpanda (Kafka API) |
| Warehouse | PostgreSQL 16 / Supabase |
| Transformations | dbt-core |
| Orchestration | Apache Airflow 2.10 |
| Ingestion | Python 3.12 + `httpx` + `aiokafka` |
| API | FastAPI + `sse-starlette` |
| Agent | LangGraph 1.x + Pydantic AI |
| RAG | LlamaIndex + Pinecone + Docling |
| Frontend | Next.js 16 + shadcn/ui + Biome |
| LLM observability | LangSmith |
| App observability | Logfire |
| Deploy | AWS EC2 spot + Bedrock + Supabase + Redpanda Cloud + Vercel |

[:octicons-arrow-right-24: Full tech-stack table](stack.md){ .md-button }
[:octicons-arrow-right-24: Architecture deep-dive](architecture.md){ .md-button .md-button--primary }

## About the author

Built by **[Humberto Slomeu](https://github.com/hcslomeu)** — AI engineer
available for hire.

[:fontawesome-brands-github: GitHub](https://github.com/hcslomeu) ·
[:fontawesome-brands-linkedin: LinkedIn](https://www.linkedin.com/in/hcslomeu/) ·
[:material-source-repository: Source code](https://github.com/hcslomeu/tfl-monitor)
