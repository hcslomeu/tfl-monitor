---
hide:
  - navigation
  - toc
---

# tfl-monitor

> A real-time data + AI engineering portfolio: a **live Transport for London
> proxy** with a LangGraph chat agent whose tools query TfL live.

<div class="grid cards" markdown>

-   :material-train-variant:{ .lg .middle } **Live operational data**

    ---

    `/status/live` and `/disruptions/recent` read through to the TfL Unified
    API on demand, cached 30 seconds at the CDN. No broker, no warehouse, no
    database (ADR 014, ADR 015).

    [:octicons-arrow-right-24: Live TfL proxy](pipelines/ingestion.md)

-   :material-robot-outline:{ .lg .middle } **Agent grounded in live data**

    ---

    LangGraph routes between typed tools: live status, disruptions, journey
    planning, and arrivals. Every step traced in LangSmith.

    [:octicons-arrow-right-24: LangGraph agent](pipelines/agent.md)

-   :material-api:{ .lg .middle } **Contract-pinned API**

    ---

    Four endpoints, RFC 7807 errors, SSE chat, and OpenAPI 3.1 as the
    contract the frontend regenerates its types from.

    [:octicons-arrow-right-24: FastAPI surface](pipelines/api.md)

-   :material-chart-line:{ .lg .middle } **Production-ready observability**

    ---

    LangSmith for LLM/agent decisions, Logfire for FastAPI requests and TfL
    calls. Zero self-hosted telemetry to babysit.

    [:octicons-arrow-right-24: Observability](observability.md)

-   :material-cloud-outline:{ .lg .middle } **Nothing to operate**

    ---

    A stateless FastAPI function and a Next.js app, both on Vercel. Spend is
    capped by Vercel Spend Management and an Anthropic workspace limit.

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

"Any disruptions on the Elizabeth line?"
   → query_recent_disruptions → live TfL /Line/Mode/{modes}/Status?detail=true

"Plan a journey from Oxford Circus to Bank."
   → plan_journey_tool → live TfL /Journey/JourneyResults

"When's the next train at King's Cross?"
   → get_arrivals_tool → live TfL /StopPoint/{id}/Arrivals
```

## Why this exists

A portfolio that demonstrates the full data + AI engineering loop on a
realistic public dataset, not a CRUD demo or a notebook prototype:

- **A live proxy that knows what not to store.** The warehouse was decommissioned
  after it bricked the free-tier database three times; serving TfL live removed
  the disk-full failure class entirely (ADR 014).
- **Cut what has no reader.** Once RAG was dropped, Postgres held nothing the
  UI read, so ADR 015 removed the database and moved the API to a stateless
  Vercel function.
- **An agent grounded in real data.** Typed, Pydantic-validated tools hit the
  live TfL API; journey and arrivals answers render as structured cards.
- **Everything traced.** LangSmith answers "why did the agent decide X?";
  Logfire answers "which TfL endpoint is throttling us?".

## Tech stack at a glance

| Layer | Choice |
|-------|--------|
| Data source | TfL Unified API, read-through on demand |
| Ingestion | Python 3.12 + `httpx` (async, retry) |
| API | FastAPI + `sse-starlette` |
| Agent | LangGraph 1.x `create_react_agent` |
| LLM | Anthropic API (`ChatAnthropic`, default `claude-haiku-5-5`) |
| Frontend | Next.js 16 + shadcn/ui + Biome |
| LLM observability | LangSmith |
| App observability | Logfire |
| Hosting | Vercel (API function in `lhr1` + Next.js) |

[:octicons-arrow-right-24: Full tech-stack table](stack.md){ .md-button }
[:octicons-arrow-right-24: Architecture deep-dive](architecture.md){ .md-button .md-button--primary }

## About the author

Built by **[Humberto Slomeu](https://github.com/hcslomeu)**, AI engineer
available for hire.

[:fontawesome-brands-github: GitHub](https://github.com/hcslomeu) ·
[:fontawesome-brands-linkedin: LinkedIn](https://www.linkedin.com/in/hcslomeu/) ·
[:material-source-repository: Source code](https://github.com/hcslomeu/tfl-monitor)
