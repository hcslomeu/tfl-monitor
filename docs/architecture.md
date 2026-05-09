# Architecture

A bird's-eye view of how data flows from TfL into the dashboard, with every
component pinned to a directory in the repo.

## System diagram

```mermaid
flowchart LR
    subgraph SRC[External sources]
      TFL[TfL Unified API]
      PDF[TfL strategy PDFs]
    end

    subgraph INGEST[Streaming ingestion]
      P1[line-status producer]
      P2[arrivals producer]
      P3[disruptions producer]
      KAFKA[(Redpanda<br/>Kafka topics)]
      C1[line-status consumer]
      C2[arrivals consumer]
      C3[disruptions consumer]
    end

    subgraph WAREHOUSE[Postgres warehouse]
      RAW[(raw.*<br/>JSONB)]
      ANALYTICS[(analytics.*<br/>marts)]
    end

    subgraph DBT[dbt transformations]
      STG[staging]
      MART[marts + exposures]
    end

    subgraph RAG[RAG layer]
      DOCLING[Docling parser]
      EMB[OpenAI embeddings]
      PINE[(Pinecone<br/>tfl-strategy-docs)]
    end

    subgraph SERVE[Serving layer]
      AGENT[LangGraph agent<br/>5 typed tools]
      API[FastAPI<br/>/status /reliability<br/>/disruptions /bus<br/>/chat/stream SSE]
      WEB[Next.js dashboard]
    end

    subgraph OBS[Observability]
      LS[LangSmith]
      LF[Logfire]
    end

    TFL -->|httpx async polling| P1
    TFL -->|httpx async polling| P2
    TFL -->|httpx async polling| P3
    P1 -->|Pydantic event| KAFKA
    P2 -->|Pydantic event| KAFKA
    P3 -->|Pydantic event| KAFKA
    KAFKA --> C1 --> RAW
    KAFKA --> C2 --> RAW
    KAFKA --> C3 --> RAW
    RAW --> STG --> MART --> ANALYTICS
    PDF --> DOCLING --> EMB --> PINE
    ANALYTICS --> AGENT
    PINE --> AGENT
    AGENT --> API
    API -->|REST + SSE| WEB

    AGENT -.traces.-> LS
    API -.spans.-> LF
    INGEST -.spans.-> LF
    WAREHOUSE -.queries.-> LF
```

## Component-to-directory map

| Layer | Directory | Runtime |
|-------|-----------|---------|
| Async TfL client | [`src/ingestion/tfl_client/`](https://github.com/hcslomeu/tfl-monitor/tree/main/src/ingestion/tfl_client) | Python 3.12 |
| Producers (×3) | [`src/ingestion/producers/`](https://github.com/hcslomeu/tfl-monitor/tree/main/src/ingestion/producers) | aiokafka |
| Consumers (×3) | [`src/ingestion/consumers/`](https://github.com/hcslomeu/tfl-monitor/tree/main/src/ingestion/consumers) | aiokafka + psycopg |
| Broker | [`docker-compose.yml`](https://github.com/hcslomeu/tfl-monitor/blob/main/docker-compose.yml) | Redpanda local; Redpanda Cloud prod |
| Warehouse | `raw.*`, `ref.*`, `analytics.*` schemas | Postgres 16 / Supabase |
| dbt project | [`dbt/`](https://github.com/hcslomeu/tfl-monitor/tree/main/dbt) | dbt-core 1.9 |
| Orchestration | [`airflow/dags/`](https://github.com/hcslomeu/tfl-monitor/tree/main/airflow/dags) | Airflow 2.10 LocalExecutor |
| RAG ingestion | [`src/rag/`](https://github.com/hcslomeu/tfl-monitor/tree/main/src/rag) | Docling + OpenAI + Pinecone |
| Agent | [`src/api/agent/`](https://github.com/hcslomeu/tfl-monitor/tree/main/src/api/agent) | LangGraph + Pydantic AI |
| API | [`src/api/`](https://github.com/hcslomeu/tfl-monitor/tree/main/src/api) | FastAPI + sse-starlette |
| Frontend | [`web/`](https://github.com/hcslomeu/tfl-monitor/tree/main/web) | Next.js 16 + shadcn |
| Contracts | [`contracts/`](https://github.com/hcslomeu/tfl-monitor/tree/main/contracts) | OpenAPI + Pydantic + SQL DDL |

## Data flow walkthrough

### 1. Producers poll TfL and emit Pydantic events

Each producer is an async daemon that wakes on a fixed cadence
(`LineStatusProducer` every 30 s, `ArrivalsProducer` every 30 s across 5 NaPTAN
hubs, `DisruptionsProducer` every 300 s across 4 modes), normalises the tier-1
TfL payload into a tier-2 [Pydantic event](pipelines/ingestion.md#contracts),
and publishes to Kafka with `acks="all"` and a stable partition key.

### 2. Consumers idempotently land into `raw.*`

`RawEventConsumer[E]` is generic over the event type; `RawEventWriter(table)`
runs `INSERT … ON CONFLICT (event_id) DO NOTHING` over a single async psycopg
connection with reconnect-on-`OperationalError`. Lag is traced on every span.

### 3. dbt stages and marts

Staging models (`stg_line_status`, `stg_arrivals`, `stg_disruptions`) unnest
JSONB into typed columns with defensive `row_number()` dedup. Marts are
incremental `merge` on stable composite grains and ship with generic + singular
tests.

```mermaid
flowchart TB
    raw_line_status[(raw.line_status<br/>JSONB)] --> stg_line_status[stg_line_status]
    raw_arrivals[(raw.arrivals)] --> stg_arrivals[stg_arrivals]
    raw_disruptions[(raw.disruptions)] --> stg_disruptions[stg_disruptions]

    stg_line_status --> reli_daily[mart_tube_reliability_daily]
    reli_daily --> reli_summary[mart_tube_reliability_daily_summary]
    stg_disruptions --> disruption_mart[mart_disruptions_daily]
    stg_arrivals --> bus_mart[mart_bus_metrics_daily]
```

### 4. RAG ingest is conditional and idempotent

`uv run python -m rag.ingest` resolves the live PDF URL on each landing page,
issues conditional `If-None-Match` / `If-Modified-Since` GETs, parses with
Docling's `HybridChunker`, async-batches OpenAI embeddings (100/req, retry on
429), and upserts into Pinecone with `sha256("{url}::{idx}")` ids — one
namespace per document, delete-namespace-on-rollover for clean idempotency.

### 5. Agent fans out across five typed tools

```mermaid
graph TD
    Q[User question] --> ROUTER{LangGraph<br/>create_react_agent}
    ROUTER -->|live ops| T1[query_tube_status]
    ROUTER -->|reliability| T2[query_line_reliability]
    ROUTER -->|disruptions| T3[query_recent_disruptions]
    ROUTER -->|bus| T4[query_bus_punctuality]
    ROUTER -->|strategy| T5[search_tfl_docs]

    T1 --> WH[(warehouse)]
    T2 --> WH
    T3 --> WH
    T4 --> WH
    T5 --> PC[(Pinecone)]

    T2 -.normalisation.-> PA[Pydantic AI<br/>Haiku LineId extractor]
```

`compile_agent` returns `None` if any of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
/ `PINECONE_API_KEY` is missing, so `/chat/stream` 503s while the history
endpoint keeps working off `DATABASE_URL` alone.

### 6. SSE projection over LangGraph events

```mermaid
sequenceDiagram
  participant W as Web (chat-view)
  participant A as FastAPI /chat/stream
  participant G as LangGraph
  participant DB as analytics.chat_messages
  W->>A: POST {thread_id, message}
  A->>DB: INSERT user turn
  A->>G: agent.astream(stream_mode=["messages","updates"])
  G-->>A: token / tool / token …
  A-->>W: data: {"type":"token",...}\n\n
  G-->>A: end
  A->>DB: INSERT assistant turn (concatenated tokens)
  A-->>W: data: {"type":"end",...}\n\n
```

## Contracts

`contracts/` is the single source of truth for every cross-service interface:

```mermaid
graph LR
    subgraph C[contracts/]
      OAPI[openapi.yaml]
      PYD[schemas/*.py]
      SQL[sql/*.sql]
      DBTSRC[dbt_sources.yml]
    end

    OAPI --> WEB[web/lib/types.ts<br/>via openapi-typescript]
    OAPI --> API[FastAPI route signatures]
    PYD --> PROD[producers]
    PYD --> CONS[consumers]
    SQL --> PG[Postgres DDL]
    SQL --> DBTSRC
    DBTSRC --> DBT[dbt sources]
```

Two tiers of Pydantic schemas separate the messy outside world from the clean
internal wire format — see [tier-1 vs tier-2](pipelines/ingestion.md#contracts).

## Related ADRs

The handful of cross-cutting decisions worth a paper trail:

- [001 — Redpanda over Apache Kafka](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/001-redpanda-over-kafka.md)
- [002 — Contracts-first parallelism](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/002-contracts-first.md)
- [003 — Airflow on Railway](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/003-airflow-on-railway.md) (superseded by 006)
- [004 — Logfire + LangSmith split](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/004-logfire-langsmith-split.md)
- [005 — Raw-table defaults](https://github.com/hcslomeu/tfl-monitor/blob/main/.claude/adrs/005-raw-table-defaults.md)
- 006 — AWS Bedrock + single-EC2 deploy *(landing with TM-A5)*
