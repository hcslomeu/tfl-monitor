# Architecture

```text
TfL Unified API ──polling──▶ Redpanda (Kafka) ──▶ Postgres (raw) ──▶ dbt ──▶ marts
                                                                                │
TfL strategy PDFs ──Docling──▶ embeddings ──▶ Pinecone                          │
                                               │                                │
                                               └───────┬────────────────────────┘
                                                       ▼
                                            LangGraph agent (SQL ↔ RAG)
                                                       │
                                     FastAPI (SSE streaming) ◀┘
                                               │
                                               ▼
                                      Next.js dashboard

 Observability layered across the whole stack:
 • LangSmith   → LLM + agent traces (routing decisions, retrieval, tokens)
 • Logfire     → app + infra traces (FastAPI spans, Postgres queries, HTTP calls)
```

## Components

| Layer | Component | Runtime | Notes |
|---|---|---|---|
| Ingestion | `src/ingestion/tfl_client` | Python 3.12 | Async `httpx` client against TfL Unified API |
| Ingestion | `src/ingestion/producers` | Python 3.12 | `aiokafka` producers emitting tier-2 Kafka events |
| Broker | Redpanda | Docker (local) / Redpanda Cloud (prod) | Kafka-wire compatible, topics: `line-status`, `arrivals`, `disruptions` |
| Ingestion | `src/ingestion/consumers` | Python 3.12 | Consumes topics, writes JSONB rows into `raw.*` |
| Warehouse | Postgres 16 | Docker (local) / Supabase (prod) | Schemas: `raw`, `ref`, `analytics` |
| Transform | dbt-core + dbt-postgres | CLI | Staging / intermediate / marts under `dbt/models/` |
| Orchestration | Airflow 2.10 (dev only) / host cron (prod) | Docker (local) / Lightsail host cron (prod) | LocalExecutor for DAG development; production replaces Airflow with `/etc/cron.d/tfl-monitor` running `dbt build --target prod` against the `api` container (see ADR 006). `dbt build` gates downstream models on test pass instead of running tests separately. |
| API | FastAPI + sse-starlette | Python 3.12 | OpenAPI 3.1 contract in `contracts/openapi.yaml` |
| Agent | LangGraph 1.x + Pydantic AI | Python 3.12 | Two tools: `query_warehouse`, `search_tfl_docs` |
| RAG | LlamaIndex + Pinecone + Docling | Python 3.12 | Hybrid retrieval over TfL strategy PDFs |
| Frontend | Next.js 16 + shadcn/ui (Radix + Nova) | Node 22 | Biome only, TS types generated from OpenAPI; upgrade from spec's v15 documented in PROGRESS.md |

## Contracts

`contracts/` is the single source of truth. Two tiers of Pydantic schemas:

- **Tier-1** (`contracts/schemas/tfl_api.py`) — raw TfL Unified API shapes
  (camelCase, nested). Ingestion parses these on the wire.
- **Tier-2** (`contracts/schemas/{line_status,arrivals,disruptions}.py`) —
  internal Kafka event wire format (snake_case, flat). Producers emit
  these; consumers and downstream services speak only this tier.

Normalisation tier-1 → tier-2 is the ingestion client's job (TM-B1+).

## Observability split

| Question | Tool |
|---|---|
| How did the agent arrive at that answer? | LangSmith |
| Which TfL endpoint is throttling us? | Logfire |
| How many tokens did this conversation cost? | LangSmith |
| Why is this endpoint p99 latency high? | Logfire |
| Did the retriever pull the right chunks? | LangSmith |
| Is the Kafka consumer keeping up? | Logfire |

See [ADR 004](./.claude/adrs/004-logfire-langsmith-split.md).

## Deployment

| Piece | Host |
|---|---|
| API + ingestion producers + ingestion consumers | AWS Lightsail (eu-west-2), shared with alpha-whale + portfolio-humberto |
| LLM (Sonnet 4.5 + Haiku 4.5) | AWS Bedrock (eu-west-2 cross-region inference profiles) |
| Reverse proxy + TLS | Shared Caddy at `/opt/caddy/` on the Lightsail host, Let's Encrypt HTTP-01 |
| DNS | Cloudflare (`humbertolomeu.com`, DNS only) |
| Frontend | Vercel (`tfl-monitor.humbertolomeu.com`) |
| Postgres | Supabase free tier |
| Kafka | Redpanda Cloud Serverless free tier |
| Vector DB | Pinecone serverless |
| Periodic jobs | `/etc/cron.d/tfl-monitor` on the host (replaces Airflow in prod — see ADR 006) |
| CI/CD | GitHub Actions → SSH rsync + `scripts/deploy.sh`, pinned host key |

## Related ADRs

- [001 — Redpanda over Apache Kafka](./.claude/adrs/001-redpanda-over-kafka.md)
- [002 — Contracts-first parallelism](./.claude/adrs/002-contracts-first.md)
- [003 — Airflow on Railway](./.claude/adrs/003-airflow-on-railway.md) (superseded by 006)
- [004 — Logfire + LangSmith split](./.claude/adrs/004-logfire-langsmith-split.md)
- [005 — Raw-table defaults](./.claude/adrs/005-raw-table-defaults.md)
- [006 — AWS Bedrock + shared Lightsail deploy](./.claude/adrs/006-aws-deploy.md)
