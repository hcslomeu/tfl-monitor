# TM-32 — RAG migration: Bedrock embeddings + pgvector (Bedrock-only)

Status: in progress. Branch: `feature/TM-32-rag-pgvector-bedrock`.

## Problem

`POST /api/v1/chat/stream` returns `503 "Chat agent is not configured"` in
production. Root cause: `compile_agent` (`src/api/agent/graph.py:93`)
returns `None` because it requires `OPENAI_API_KEY` **and**
`PINECONE_API_KEY`, both intentionally empty on the Lightsail box. The
LLM backend (Bedrock) is fully wired; only the RAG layer's OpenAI +
Pinecone dependency blocks the agent.

Author decision: **AWS Bedrock only — no OpenAI, no Pinecone.** Migrate
RAG embeddings to Bedrock Titan v2 and the vector store to pgvector on
the existing Postgres. Refresh the corpus to current TfL PDFs.

## Locked decisions

- **LLM**: Bedrock (already live, unchanged).
- **Embeddings**: `amazon.titan-embed-text-v2:0`, 1024-dim, via
  `llama-index-embeddings-bedrock` (`BedrockEmbedding`). boto3 standard
  credential chain (same AWS keys already on the box).
- **Vector store**: pgvector on the existing Postgres, managed by
  LlamaIndex `PGVectorStore` (auto-created table). No `contracts/sql`
  change — the vector table is infra-managed, exactly as Pinecone was
  external. `doc_id` becomes a metadata filter (replaces namespaces).
- **Corpus** (6 direct PDFs, all verified `200/206 application/pdf`):
  | doc_id | title | url |
  |---|---|---|
  | `business_plan_2026` | 2026 Business Plan | content.tfl.gov.uk/2026-business-plan-acc.pdf |
  | `mts_delivery_2024_25` | Delivering the MTS 2024-25 | content.tfl.gov.uk/delivering-the-mayors-transport-strategy-2024-25-acc.pdf |
  | `bus_action_plan` | Bus Action Plan | content.tfl.gov.uk/bus-action-plan.pdf |
  | `vision_zero` | Vision Zero action plan | content.tfl.gov.uk/vision-zero-action-plan.pdf |
  | `cycling_action_plan` | Cycling action plan | content.tfl.gov.uk/cycling-action-plan.pdf |
  | `travel_in_london_2025` | Travel in London 2025 | content.tfl.gov.uk/travel-in-london-2025-consolidated-estimates-of-total-travel-and-mode-shares-acc.pdf |

## Connection-mode risk (must verify)

`PGVectorStore` uses SQLAlchemy + `asyncpg` (async) / `psycopg2` (sync).
`asyncpg` issues prepared statements, which break against the Supabase
**transaction pooler** (port 6543, pgbouncer). The warehouse already hit
this class of bug (napkin → Domain Behavior Guardrail #1). RAG must use
the Supabase **direct/session connection (port 5432)** or set
`statement_cache_size=0`. Decision: introduce `RAG_DATABASE_URL` (direct
5432) distinct from the app's pooled `DATABASE_URL`; fall back to
`DATABASE_URL` when unset (local dev). Verify a live retrieval against
the real Supabase endpoint before declaring done.

## Phases

1. **Deps + config** — `pyproject.toml`: drop `pinecone`,
   `llama-index-vector-stores-pinecone`, `openai`; add
   `llama-index-vector-stores-postgres`, `llama-index-embeddings-bedrock`,
   `pgvector`. `uv lock`. Rewrite `src/rag/config.py`: drop OpenAI/Pinecone
   fields; add `bedrock_region`, `embedding_model`
   (`amazon.titan-embed-text-v2:0`), `embedding_dimensions` (1024),
   `pgvector_table`, `rag_database_url`.
2. **Sources** — `src/rag/sources.json` → the 6 docs (direct
   `resolved_url`, no landing-page scrape needed).
3. **Ingestion** — `src/rag/embed.py` (OpenAI batching → delete; embedding
   handled by `BedrockEmbedding` at index-build time), `src/rag/upsert.py`
   (Pinecone → `PGVectorStore`), `src/rag/ingest.py` (drop pinecone/openai
   factories, wire Bedrock + pgvector). Keep the conditional-fetch +
   Docling parse stages unchanged.
4. **Retrieval + compile** — `src/api/agent/rag.py`
   (`PineconeVectorStore` + `OpenAIEmbedding` → `PGVectorStore` +
   `BedrockEmbedding`; namespace fan-out → `doc_id` metadata filter).
   `src/api/agent/graph.py` (compile gate: require pool + Bedrock backend;
   drop OpenAI/Pinecone requirement; `search_tfl_docs` available when the
   pgvector table is reachable).
5. **Local infra** — `docker-compose.yml` postgres image
   `postgres:16` → `pgvector/pgvector:pg16`; ensure
   `CREATE EXTENSION IF NOT EXISTS vector` on init.
6. **Tests** — rewrite `tests/rag/{test_embed,test_upsert,test_ingest}`,
   `tests/agent/{test_rag_tool,test_graph_compile}` for the new backend
   with fakes (no live Bedrock/PG in unit tests).
7. **Prod cutover** (explicit auth per step) — enable `vector` extension
   on Supabase; update box `.env` (drop `OPENAI_API_KEY`/`PINECONE_*`, add
   embed model + table + `RAG_DATABASE_URL`); re-ingest corpus into
   Supabase (Bedrock cost); `docker compose up -d --force-recreate api`;
   smoke `POST /chat/stream` live.

## Success criteria

- Local: `make check` green; agent compiles with Bedrock + `DATABASE_URL`
  alone, zero OpenAI/Pinecone references in `src/`.
- Prod: `POST /api/v1/chat/stream` streams `token` + `tool` + `end`
  frames; `search_tfl_docs` returns snippets from the new corpus.

## Out of scope

- `contracts/sql` schema changes (vector table is LlamaIndex-managed).
- Warehouse migration to self-hosted Postgres (TM-31 / #108).
- New agent tools — journey/arrivals (PR-C / #103).
