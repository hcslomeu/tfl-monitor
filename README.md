# tfl-monitor

> A real-time data + AI engineering portfolio: streaming Transport for London
> feeds into a dbt-modelled warehouse, with a LangGraph agent that routes
> between SQL over the warehouse and RAG over TfL strategy documents.

[![CI](https://github.com/hcslomeu/tfl-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/hcslomeu/tfl-monitor/actions/workflows/ci.yml)
[![docs](https://github.com/hcslomeu/tfl-monitor/actions/workflows/docs.yml/badge.svg)](https://hcslomeu.github.io/tfl-monitor/)
[![python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![licence](https://img.shields.io/badge/licence-MIT-green.svg)](./LICENSE)

🚧 **Under active deployment** — the codebase is feature-complete; TM-A5
ships the AWS Bedrock + EC2 deploy.

- 📚 **Documentation**: <https://hcslomeu.github.io/tfl-monitor/>
- 🏛️ **Architecture**: [`ARCHITECTURE.md`](./ARCHITECTURE.md) ·
  [docs/architecture](https://hcslomeu.github.io/tfl-monitor/architecture/)
- 🧱 **Setup**: [`SETUP.md`](./SETUP.md)
- ✅ **WP ledger**: [`PROGRESS.md`](./PROGRESS.md)
- 🚀 **Live demo**: shipping with TM-A5 + TM-E4
- 🎬 **Demo video**: shipping with TM-F1

---

## What this project is

tfl-monitor ingests live feeds from the Transport for London Unified API —
line status, arrivals, and disruptions across Tube, Elizabeth Line,
Overground, and DLR — into a Kafka-backed streaming pipeline, transforms them
into a dbt-modelled Postgres warehouse, and exposes a Next.js dashboard plus
a conversational agent that can answer two different kinds of question:

- **"Which Tube line had the worst reliability last week?"** — answered by an
  agent that runs a typed query against the warehouse.
- **"What's TfL's strategy for Piccadilly Line upgrades?"** — answered by RAG
  retrieval over TfL's Business Plan, the Mayor's Transport Strategy, and
  TfL's Annual Report.

The agent routes between these two modes automatically and cites either the
SQL rows or the exact document chunks it used.

## Why this project exists

A portfolio that demonstrates the **full data + AI engineering loop** on a
realistic public dataset, not a CRUD demo or a notebook prototype:

- Streaming ingestion that earns its Kafka broker (not a cron job in disguise)
- A warehouse modelled properly in dbt with tests, documentation, and lineage
- An AI agent that doesn't hallucinate because it's wired to real data and
  real documents
- Production deployment for ~$6/month total, observable end-to-end

## Architecture at a glance

```text
TfL Unified API ──polling──▶ Redpanda (Kafka) ──▶ Postgres (raw) ──▶ dbt ──▶ marts
                                                                               │
TfL strategy PDFs ──Docling──▶ embeddings ──▶ Pinecone                         │
                                              │                                │
                                              └──────┬─────────────────────────┘
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

Full diagram with mermaid + per-pipeline walkthroughs in
[the docs site](https://hcslomeu.github.io/tfl-monitor/architecture/).

## Tech stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Streaming broker | Redpanda (Kafka API) | Single binary, identical local ↔ prod |
| Warehouse | PostgreSQL 16 / Supabase | JSONB-native, mature dbt adapter |
| Transformations | dbt-core + dbt-postgres | Tests, docs, lineage as code |
| Orchestration | Apache Airflow 2.10+ | LocalExecutor; portfolio-relevant skill |
| Ingestion | `httpx` + `aiokafka` + Pydantic v2 | Async retry, typed events end-to-end |
| API | FastAPI + `sse-starlette` | Async, typed, OpenAPI 3.1 auto-emitted |
| Agent | LangGraph 1.x | Stateful graph with five typed tools |
| Structured extraction | Pydantic AI | Tool-level typed LLM calls (Haiku normaliser) |
| RAG | LlamaIndex + Pinecone + Docling | Conditional GET, namespace per document |
| LLMs | Claude Sonnet 3.5 + Haiku 3.5 | Top-of-class tool calling |
| LLM observability | LangSmith | Auto-instruments every node and tool call |
| App observability | Logfire | OpenTelemetry-native FastAPI / Postgres / HTTP |
| Frontend | Next.js 16 + shadcn/ui | Server components, Tailwind v4, Radix Nova |
| Lint / format | Ruff (Python), Biome (TS) | Single tool per ecosystem |

Full table — including the rejection rationale per choice — is in
[`docs/stack`](https://hcslomeu.github.io/tfl-monitor/stack/).

## Engineering highlights

### Contracts-first parallelism

Every cross-track interface lives in [`contracts/`](./contracts):

- Pydantic v2 schemas for every Kafka topic
- OpenAPI 3.1 spec for every API endpoint
- Postgres DDL for every raw table
- dbt `sources.yml` derived from the DDL

The frontend regenerates TypeScript types from the OpenAPI spec; the
ingestion layer serialises Pydantic models onto Kafka; dbt stages the raw
tables into typed columns. CI gates a bidirectional drift test across all
four artefacts.

### Kafka earns its place

TfL updates line status every 30 seconds and disruptions continuously. Kafka
gives us decoupling (producers keep polling while consumers redeploy),
**replay** (rewinding a topic re-hydrates the warehouse), and **fan-out**
(multiple consumer groups read the same topic). We exploit all three; we did
not pay the cost of Kafka for its own sake.

### dbt over raw SQL

Around ten staging, intermediate, and mart models with dependencies; generic
tests for `unique`, `not_null`, and referential integrity; eight singular
tests for business invariants; auto-generated lineage and exposures wiring
marts to the consuming endpoints.

### The agent routes between SQL and RAG

A LangGraph `create_react_agent` exposes five typed tools — four wrap the
warehouse-backed FastAPI fetchers (so there is one source of truth per
query) and the fifth is a LlamaIndex retriever fanning out across the three
Pinecone namespaces. Tool docstrings declare assumptions that reach the
model (e.g. the documented bus-punctuality proxy). Every step is traced in
LangSmith.

### Observability split

Two hosted tools, zero self-hosted telemetry:

- **LangSmith** answers *"why did the agent decide that?"*
- **Logfire** answers *"why is this endpoint slow?"*

Both ride on free tiers. No Prometheus / Grafana / OTel collector to babysit.

## Local development

Prerequisites: Docker, `uv`, `pnpm`, `make`, `git`. Free TfL API key, plus
accounts on Pinecone, OpenAI, Anthropic (or AWS Bedrock), LangSmith, Logfire.
See [`SETUP.md`](./SETUP.md) for the full quick-start.

```bash
git clone git@github.com:hcslomeu/tfl-monitor.git
cd tfl-monitor
cp .env.example .env
# fill in the keys you have

make bootstrap        # install Python + Node deps
make up               # start Postgres, Redpanda, Airflow
make seed             # load fixtures into local Postgres
make check            # lint + tests + build, both halves
```

In two more terminals:

```bash
uv run task api       # FastAPI on :8000
pnpm --dir web dev    # dashboard on :3000
```

Visit <http://localhost:3000>.

Tear it down with `make down` (preserves data) or `make clean` (wipes
volumes).

### Documentation site

Local preview of the MkDocs Material site:

```bash
uv sync --group docs
uv run task docs-serve   # http://127.0.0.1:8001
```

Build for offline review:

```bash
uv run task docs-build
open site/index.html
```

The site is published to GitHub Pages on every merge to `main` via
`.github/workflows/docs.yml`.

### RAG ingestion (TM-D4)

Three TfL strategy PDFs are fetched, parsed via Docling, embedded with OpenAI
`text-embedding-3-small`, and upserted into the Pinecone serverless index
`tfl-strategy-docs`. The fetcher follows the canonical landing pages to
discover the current direct-PDF URL, then issues conditional
`If-None-Match` / `If-Modified-Since` requests so re-runs only download what
has changed.

```bash
uv run python -m rag.ingest                # default — only refetch what changed
uv run python -m rag.ingest --refresh-urls # rewrite resolved PDF URLs
uv run python -m rag.ingest --force-refetch
uv run python -m rag.ingest --dry-run      # skip Pinecone upsert
```

Cost: a full re-embedding of all three PDFs runs at well under £0.20 one-time.
Conditional GETs and stable Pinecone IDs mean steady-state runs incur
near-zero spend.

## Production deployment (TM-A5)

| Layer | Host | $/mo |
|-------|------|------|
| Backend compute (FastAPI + ingestion + Airflow) | AWS EC2 t4g.small spot via ASG | ~3-4 |
| LLM | AWS Bedrock (Claude Sonnet 3.5 + Haiku 3.5) | ~2-3 |
| Postgres warehouse + Airflow metadata | Supabase free | 0 |
| Kafka broker | Redpanda Cloud Serverless free | 0 |
| Vector DB | Pinecone serverless free | 0 |
| Frontend | Vercel hobby free | 0 |
| HTTPS | DuckDNS subdomain + Caddy auto-LE | 0 |
| Image registry | GHCR (public repo) | 0 |
| Observability | Logfire + LangSmith free tiers | 0 |
| **Steady-state target** | | **~$5-8** |

Full design and provisioning runbook in
[`docs/deployment`](https://hcslomeu.github.io/tfl-monitor/deployment/) and
[`.claude/specs/TM-A5-plan.md`](./.claude/specs/TM-A5-plan.md).

## Status

Codebase is feature-complete; the deploy track is the last open work.
Source of truth for the WP ledger is [`PROGRESS.md`](./PROGRESS.md), mirrored
in the [docs roadmap](https://hcslomeu.github.io/tfl-monitor/roadmap/).

| Phase | Title | Status |
|-------|-------|--------|
| 0 | Contracts and scaffold | ✅ |
| 1-2 | Compose, scaffold, dbt + FastAPI skeleton, TfL client | ✅ |
| 3 | line-status producer + consumer, first mart, `/status/live` + `/status/history` + `/reliability/{id}`, Network Now mock + wired | ✅ |
| 4 | arrivals + disruptions topics, remaining marts + exposures, `/disruptions/recent` + `/bus/{id}/punctuality`, Disruption Log view | ✅ |
| 5 | Airflow DAGs, RAG ingestion (Docling → Pinecone) | ✅ |
| 6 | LangGraph agent + Pydantic AI normaliser, Chat view with SSE | ✅ |
| 7 | AWS Bedrock + EC2 deploy, Vercel deploy, demo video, live URL | 🚧 |

## Folder map

```text
tfl-monitor/
├─ contracts/        # OpenAPI + Pydantic + DDL — single source of truth
├─ src/
│  ├─ api/           # FastAPI app + LangGraph agent + Pydantic AI extraction
│  ├─ ingestion/     # Async TfL client + producers + consumers
│  ├─ rag/           # Docling → OpenAI → Pinecone ingestion
│  └─ agent/         # Legacy graph (kept for parity until TM-A5 collapse)
├─ dbt/              # Staging + marts + tests + exposures
├─ airflow/          # DAGs (dbt nightly, RAG weekly)
├─ web/              # Next.js 16 + shadcn dashboard
├─ tests/            # Pytest unit + integration suites
├─ scripts/          # Fixture seeding + TfL sample fetcher
├─ docs/             # MkDocs Material site (this README's expanded form)
└─ .claude/          # ADRs + WP specs + napkin (coordination memory)
```

Each folder has its own `README.md` walking its purpose, contents, and
gotchas — see the docs site for the curated walkthrough.

## Data sources and attribution

- **TfL Unified API** — live operational feeds. Powered by TfL Open Data.
  Contains OS data © Crown copyright and database rights.
- **TfL publications** — Mayor's Transport Strategy, TfL Business Plan, TfL
  Annual Report. Public documents used under their published terms.

No personal data is collected, stored, or processed by tfl-monitor.

## Licence

MIT. See [`LICENSE`](./LICENSE).

## Author

Built by **[Humberto Slomeu](https://github.com/hcslomeu)** — AI engineer
available for hire.
[LinkedIn](https://www.linkedin.com/in/hcslomeu/)
