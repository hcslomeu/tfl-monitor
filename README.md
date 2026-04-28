# tfl-monitor

> A real-time data platform for Transport for London's network — streaming pipeline, dbt-modelled warehouse, and a RAG agent that answers questions about live operations and TfL strategy.

🚧 **Under active development.** Live demo link coming with deployment (Phase 7).

- **Live demo**: 🚧 via TM-A5 + TM-E4
- **Demo video**: 🚧 via TM-F1
- **Architecture**: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- **Setup**: [`SETUP.md`](./SETUP.md)

---

## What this project is

tfl-monitor ingests live feeds from the Transport for London Unified API — line status, arrivals, and disruptions across Tube, Elizabeth Line, Overground, and DLR — into a Kafka-backed streaming pipeline, transforms them into a dbt-modelled Postgres warehouse, and exposes a Next.js dashboard plus a conversational agent that can answer two different kinds of question:

- **"Which Tube line had the worst reliability last week?"** — answered by an agent that writes SQL against the warehouse.
- **"What's TfL's strategy for Piccadilly Line upgrades?"** — answered by RAG retrieval over TfL's Business Plan, the Mayor's Transport Strategy, and TfL's Annual Report.

The agent routes between these two modes automatically.

## Why this project exists

Portfolio project demonstrating **end-to-end data + AI engineering** on a realistic public dataset:

- Streaming ingestion that earns its Kafka broker (not a cron job in disguise)
- A warehouse modelled properly in dbt with tests, documentation, and lineage
- An AI agent that doesn't hallucinate because it's wired to real data and real documents
- Everything deployed, observable, reproducible

## Architecture at a glance

```
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

Full diagram and component table in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Streaming broker | Redpanda (Kafka-compatible) | Kafka API, single binary, same code local and in Redpanda Cloud |
| Warehouse | PostgreSQL 16 | Simple, Supabase-compatible, fits the dataset |
| Transformations | dbt-core + dbt-postgres | Tests, docs, lineage — the modern warehouse standard |
| Batch orchestration | Apache Airflow 2.10+ | DAGs for static data ingest and nightly dbt rebuilds |
| Ingestion | Python 3.12 + `httpx` + `aiokafka` | Async producers with retry, Pydantic-validated messages |
| API | FastAPI + `sse-starlette` | Async, typed, great OpenAPI story |
| Agent | LangGraph 1.x | Stateful graph with SQL tool and RAG tool |
| Structured LLM calls | Pydantic AI | Type-safe extraction inside tools (not the main agent) |
| RAG | LlamaIndex + Pinecone + Docling | Hybrid retrieval over TfL PDFs |
| Validation | Pydantic v2 | Every data boundary in the system |
| LLM observability | LangSmith | Traces every agent decision, tool call, retrieval |
| App observability | Logfire | FastAPI, Postgres, HTTP — OpenTelemetry-native |
| Frontend | Next.js 16 + shadcn/ui + claude.design | Server components, typed API client from OpenAPI |
| Deploy | Railway + Vercel + Supabase + Redpanda Cloud + Pinecone | Free tiers where possible; ~£5/mo for Airflow on Railway |

## Engineering highlights

### Contracts-first, enabling parallel agent work

Every cross-track interface lives in [`contracts/`](./contracts):

- Pydantic v2 schemas for every Kafka topic
- OpenAPI 3.1 spec for every API endpoint
- Postgres DDL for every raw table
- dbt `sources.yml` derived from the DDL

The frontend generates TypeScript types from the OpenAPI spec. The ingestion layer serialises Pydantic models onto Kafka. dbt stages the raw tables into typed columns. Change the contract, regenerate everywhere — a single source of truth for the shape of the system.

### Kafka earns its place

TfL updates line status roughly every 30 seconds and disruptions continuously. At four polling endpoints with sub-minute cadence, Kafka gives us:

- **Decoupling** — producers keep polling even if consumers are deploying
- **Replay** — we can rewind topics to backfill a new consumer
- **Fan-out** — multiple consumers (warehouse writer, live dashboard pusher, agent context hydrator) read the same topic

A cron-to-Postgres pipeline would work; it would also lock us into a single consumer and lose history on restart.

### dbt over raw SQL

Roughly 10 staging, intermediate, and mart models with dependencies; automatic tests for `unique`, `not_null`, and referential integrity; an auto-generated lineage graph; documentation that ships with the code. Raw SQL scripts would also work — until a second person needs to read the codebase.

### The agent routes between SQL and RAG

A LangGraph agent exposes two tools:

- `query_warehouse(sql: str)` — executes read-only SQL against a restricted role on the mart schema
- `search_tfl_docs(query: str, top_k: int)` — hybrid (vector + BM25) retrieval over TfL strategy PDFs with reranking

A router node inspects the question and picks the right tool. Answers cite either the SQL query and its rows, or the exact document chunks used. No hallucinations — or if there are, you can see exactly where they came from, traced end-to-end in LangSmith.

### Observability split

Two hosted tools, zero self-hosted telemetry stack:

- **LangSmith** — traces every LLM call, tool invocation, retrieval step. Answers: *why did the agent pick this tool?*, *which chunks made it into the prompt?*, *how many tokens did this cost?*
- **Logfire** — instruments FastAPI, Postgres (`psycopg`), HTTP clients. Answers: *is my consumer keeping up?*, *why is this endpoint slow?*, *is TfL rate-limiting me?*

Both free tiers cover this project. No Prometheus, no Grafana, no OpenTelemetry collector to babysit.

## Local development

Prerequisites: Docker, `uv`, `pnpm`, `make`, `git`. Free TfL API key. Accounts on Pinecone, OpenAI, Anthropic, LangSmith, Logfire. See [`SETUP.md`](./SETUP.md) for the full setup.

```bash
git clone git@github.com:hcslomeu/tfl-monitor.git
cd tfl-monitor
cp .env.example .env
# edit .env with your keys

make bootstrap        # install Python + Node deps
make up               # start Postgres, Redpanda, Airflow, MinIO
make seed             # load fixtures into local Postgres
make check            # lint + tests + build

# in separate terminals:
uv run task api       # API on :8000
pnpm --dir web dev    # dashboard on :3000
```

Visit `http://localhost:3000`.

Frontend tooling (delegated to `pnpm` — never npm or yarn):

```bash
pnpm --dir web lint   # Biome (sole linter/formatter)
pnpm --dir web test   # Vitest + React Testing Library
pnpm --dir web build  # Next.js production build
```

`make check` chains the Python and TypeScript gates for both halves of
the codebase. See [`web/README.md`](./web/README.md) for the full
frontend quickstart, including how to regenerate TS types from the
OpenAPI contract.

Bring it all down with `make down` (preserves data) or `make clean` (wipes volumes).

## Status — work packages

Project built as WPs organised into parallel tracks. Track labels indicate which directories a WP touches, so at most 2 agents work simultaneously without collision.

| Phase | WP | Title | Track | Status |
|---|---|---|---|---|
| 0 | TM-000 | Contracts and scaffold | — | ⬜ |
| 1 | TM-A1 | Docker Compose + Postgres + Redpanda + Airflow | A-infra | ⬜ |
| 1 | TM-B1 | Async TfL client + fixtures | B-ingestion | ⬜ |
| 2 | TM-C1 | dbt scaffold | C-dbt | ⬜ |
| 2 | TM-D1 | FastAPI skeleton + Logfire wiring | D-api-agent | ⬜ |
| 3 | TM-B2 | `line-status` producer | B-ingestion | ⬜ |
| 3 | TM-B3 | `line-status` consumer | B-ingestion | ⬜ |
| 3 | TM-C2 | dbt staging + first mart | C-dbt | ⬜ |
| 3 | TM-D2 | Wire endpoints to Postgres | D-api-agent | ⬜ |
| 3 | TM-E1a | Next.js scaffold + shadcn + Network Now (mocked) | E-frontend | ⬜ |
| 3 | TM-E1b | Network Now wired to real `/status/live` | E-frontend | ⬜ |
| 4 | TM-B4 | arrivals + disruptions topics | B-ingestion | ⬜ |
| 4 | TM-C3 | Remaining marts + tests + exposures | C-dbt | ⬜ |
| 4 | TM-D3 | Remaining endpoints | D-api-agent | ⬜ |
| 4 | TM-E2 | Disruption Log view | E-frontend | ⬜ |
| 5 | TM-A2 | Airflow DAGs | A-infra | ⬜ |
| 5 | TM-D4 | RAG ingestion: Docling → Pinecone | D-api-agent | ⬜ |
| 6 | TM-D5 | LangGraph agent (SQL + RAG + Pydantic AI) | D-api-agent | ⬜ |
| 6 | TM-E3 | Chat view with SSE | E-frontend | ⬜ |
| 7 | TM-A3 | Supabase provisioning | A-infra | ⬜ |
| 7 | TM-A4 | Redpanda Cloud | A-infra | ⬜ |
| 7 | TM-A5 | Railway deploy (Airflow + API + agent + workers) | A-infra | ⬜ |
| 7 | TM-E4 | Vercel deploy | E-frontend | ⬜ |
| 7 | TM-F1 | README polish + demo video + live URL | F-polish | ⬜ |

## Data sources and attribution

- **TfL Unified API** — live operational feeds. Powered by TfL Open Data. Contains OS data © Crown copyright and database rights.
- **TfL publications** — Mayor's Transport Strategy, TfL Business Plan, TfL Annual Report. Public documents used under their published terms.

No personal data is collected, stored, or processed by tfl-monitor.

## Licence

MIT. See [`LICENSE`](./LICENSE).

## Author

Built by [Humberto Slomeu](https://github.com/hcslomeu) — AI engineer available for hire. [LinkedIn](https://www.linkedin.com/in/hcslomeu/)
