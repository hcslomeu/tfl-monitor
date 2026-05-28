# src/rag/

The RAG ingestion CLI: TfL strategy PDFs → PyMuPDF parse → Bedrock Titan v2
embeddings → pgvector. **Conditional** (only refetches what changed) and
**idempotent** (each changed doc is delete-then-inserted under its `doc_id`).

## Layout

```text
src/rag/
├─ __init__.py
├─ config.py        # Settings (BaseSettings) — env-driven config
├─ sources.json     # Resolved direct-PDF URLs (overwritten by --refresh-urls)
├─ sources.py       # Landing-page URL resolver (per-source allowlist)
├─ fetch.py         # Conditional GET via If-None-Match + If-Modified-Since
├─ parse.py         # PyMuPDF text extraction + LlamaIndex SentenceSplitter
├─ embeddings.py    # TitanEmbedding — Bedrock Titan v2 LlamaIndex embedding
├─ vectorstore.py   # PGVectorStore + embedding factories (shared with the agent)
├─ upsert.py        # Chunk → TextNode → pgvector (delete-then-insert per doc)
└─ ingest.py        # Orchestrator — `python -m rag.ingest`
```

## CLI

```bash
uv run python -m rag.ingest                 # only refetch what changed
uv run python -m rag.ingest --refresh-urls  # rewrite sources.json
uv run python -m rag.ingest --force-refetch # bypass ETag cache
uv run python -m rag.ingest --dry-run       # parse only, skip embed + upsert
```

If one document fails its fetch / parse / embed / upsert cycle, the others
still complete and the CLI exits non-zero so the cron / GitHub Action
surfaces the failure instead of swallowing it.

## Documents indexed

| `doc_id` | Title |
|----------|-------|
| `business_plan_2026` | TfL Business Plan 2026 |
| `mts_delivery_2024_25` | Delivering the Mayor's Transport Strategy 2024-25 |
| `bus_action_plan` | TfL Bus Action Plan |
| `vision_zero` | Vision Zero Action Plan |
| `cycling_action_plan` | Cycling Action Plan |
| `travel_in_london_2025` | Travel in London 2025 |

All six are direct `content.tfl.gov.uk` PDFs; `--refresh-urls` re-resolves a
landing page only when TfL rolls a URL stem.

## Idempotency strategy

| Stage | Mechanism |
|-------|-----------|
| Fetch | `If-None-Match` + `If-Modified-Since` from `data/cache/sources_state.json` |
| Embed | Bedrock Titan v2 `invoke_model` per chunk |
| Upsert | Delete-then-insert: `delete(ref_doc_id=doc_id)` then re-add all chunks |

A 304 cache hit skips parse + embed + upsert entirely, so steady-state runs
incur near-zero Bedrock spend.

## pgvector store shape

LlamaIndex `PGVectorStore` manages its own table (`data_<table>`), created on
first use:

```text
Table:       data_tfl_strategy_docs (schema public)
Dimension:   1024
Metric:      cosine (exact scan)
Doc scoping: metadata doc_id filter (one WHERE clause per document)
Metadata:    doc_id, doc_title, section_title, page_start, page_end, resolved_url, chunk_index
```

## Config

| Env var | Default |
|---------|---------|
| `BEDROCK_REGION` | `eu-west-2` |
| `EMBEDDING_MODEL` | `amazon.titan-embed-text-v2:0` |
| `EMBEDDING_DIMENSIONS` | `1024` |
| `PGVECTOR_TABLE` | `tfl_strategy_docs` |
| `RAG_DATABASE_URL` | (falls back to `DATABASE_URL`) |

`RAG_DATABASE_URL` must be a direct/session Postgres DSN (port 5432): the
async `asyncpg` driver's prepared statements are rejected by the Supabase
transaction pooler (port 6543).

## Tests

Unit tests with fakes for httpx / PDF parsing / Bedrock / pgvector:

| Module | Coverage |
|--------|----------|
| `sources.py` | landing-page resolver picks the right PDF URL via per-source allowlist |
| `fetch.py` | 304 short-circuit, 200 with body, ETag round-trip |
| `parse.py` | PyMuPDF pages → sentence-split chunks with stable text + page metadata |
| `embeddings.py` | Titan invoke params (dimensions/normalize), batch, query path |
| `upsert.py` | Node shape, delete-then-insert, batch sizing |
| `ingest.py` | Orchestrator wiring, dry-run, 304 skip, exit-non-zero on partial failure |
