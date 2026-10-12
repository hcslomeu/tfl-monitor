# ADR 015: Stateless API on Vercel, Anthropic direct, no RAG or Postgres

- Status: Accepted
- Date: 2026-10-12

## Context

After ADR 014 the API was a live TfL proxy plus a RAG chat, still deployed
as a Docker container on the shared AWS Lightsail box `alpha-whale-prod`
(ADR 006) behind a shared Caddy. Four things changed:

- **The box is being decommissioned.** The other tenants moved off it and
  the instance is due to be snapshotted and deleted; tfl-monitor was its
  last reason to exist.
- **Bedrock is no longer available to this project.** The IAM key the chat
  used was deactivated on 2026-10-12: the AWS account also carries another
  project's demo whose Bedrock spend is capped by a Budget + Deny that does
  not cover tfl-monitor, so any tfl-monitor Bedrock call eats that cap. The
  current Haiku/Sonnet models are not enabled on that account either.
- **The product is the live monitor and the chat, not document Q&A.** The
  RAG layer over TfL strategy PDFs (LlamaIndex + pgvector + Bedrock Titan
  embeddings) is no longer wanted: live status, disruptions, journeys and
  arrivals answer what a real-time monitor is for.
- **Postgres had no remaining reader.** Without RAG, the database held only
  a write-only chat log (`analytics.chat_messages`, never read by the UI,
  already covered by LangSmith traces) and `analytics.dim_stations`, a
  NaPTAN→name fast path that already fell back to TfL live lookups. The
  Supabase free tier had already bricked three projects (ADR 014).

## Decision

Run the API as a **stateless FastAPI function on Vercel** (Fluid compute,
Pro plan, region `lhr1`), and cut every dependency that only served RAG,
Postgres, or Bedrock.

- **Hosting:** Vercel project `tfl-monitor-api`, Git-linked to this repo.
  `pyproject.toml` `[tool.vercel] entrypoint = "src.api.main:app"`;
  `vercel.json` sets `maxDuration: 300` (SSE chat) and excludes non-runtime
  files. The public hostname `tfl-monitor-api.humbertolomeu.com` is kept so
  the frontend needs no change.
- **LLM:** Anthropic API direct via `langchain-anthropic` `ChatAnthropic`.
  Model from `CHAT_MODEL` (default `claude-haiku-5-5`), `effort: low`,
  4096-token response cap, automatic prompt caching, a 12-step LangGraph
  recursion limit. No sampling parameters (current models reject them).
  Spend is capped outside the code: the key is issued from a dedicated
  Anthropic Console workspace with a monthly spend limit. When Anthropic
  rejects a call (limit reached, auth, rate limit) the stream emits a
  readable token and `end: "error"`.
- **No database.** The lifespan opens only the `TflClient` and compiles the
  agent. Station names resolve through cached TfL `/StopPoint` lookups.
  Conversation memory stays in the agent's in-process `InMemorySaver`.
- **Cost guard:** `/api/v1/status/live` and `/api/v1/disruptions/recent`
  return `Cache-Control: public, s-maxage=30, stale-while-revalidate=30`, so
  the CDN collapses every dashboard viewer's 30-second polling into at most
  one function run per window.

**Removed:** `src/rag/` and the `search_tfl_docs` tool; the unused Pydantic
AI line-id normaliser (`extraction.py`, dead since ADR 014 removed its only
caller); `db.py`, `agent/history.py`, `GET /api/v1/chat/{thread_id}/history`
and the `ChatMessage` schema; `contracts/sql/`, `contracts/dbt_sources.yml`
and the whole `dbt/` project; the Kafka event envelopes (`Event`,
`*Event`, `LineStatusPayload`, `ArrivalPayload`) and their producer-only
normalisers; the Lightsail deploy (`deploy.yml`, `scripts/deploy.sh`,
`bootstrap-tenant.sh`, `cron-dbt-run.sh`, `infra/`, the Dockerfile) and the
local Postgres compose file. Runtime dependencies drop `boto3`,
`langchain-aws`, `pydantic-ai`, `pydantic-settings`, `psycopg`, LlamaIndex,
`pgvector`, `pymupdf`, `sqlalchemy` and dbt; the Vercel bundle is about
100 MB unzipped, down from about 550 MB.

## Consequences

- No server, broker, database, or AWS resource is left to operate. The
  Lightsail instance, the `tfl-monitor-bedrock` IAM user, and the Supabase
  project can be deleted once production runs on Vercel.
- Marginal hosting cost is expected to sit inside the Vercel Pro included
  usage; the LLM bill is bounded by the Anthropic workspace limit.
- Conversation memory is per function instance: a cold start or a request
  routed to another instance starts the thread fresh. Acceptable at
  portfolio traffic.
- Disruption cards resolve station names with TfL calls instead of a SQL
  lookup; the process-lifetime cache keeps repeat lookups free.
- Pushes to `main` no longer deploy over SSH; Vercel builds every push
  (previews for branches, production for `main`).
- **Supersedes ADR 006** (Bedrock + shared Lightsail deploy) and **ADR 013**
  (PyMuPDF for RAG ingestion). The CLAUDE.md / AGENTS.md tech-stack tables
  drop the database, batch, transformation, structured-extraction, RAG,
  vector-store, PDF and embeddings rows and switch backend hosting to
  Vercel.
