# src/rag/

The RAG ingestion CLI: TfL strategy PDFs → Docling parse → OpenAI embeddings
→ Pinecone serverless. **Conditional** (only refetches what changed) and
**idempotent** (re-running upserts the same vector ids).

## Layout

```text
src/rag/
├─ __init__.py
├─ config.py        # Settings (BaseSettings) — env-driven config
├─ sources.json     # Resolved direct-PDF URLs (overwritten by --refresh-urls)
├─ sources.py       # Landing-page URL resolver (per-source allowlist)
├─ fetch.py         # Conditional GET via If-None-Match + If-Modified-Since
├─ parse.py         # Docling DocumentConverter + HybridChunker
├─ embed.py         # Async-batched OpenAI text-embedding-3-small
├─ upsert.py        # Pinecone serverless — namespace per doc_id
└─ ingest.py        # Orchestrator — `python -m rag.ingest`
```

## CLI

```bash
uv run python -m rag.ingest                 # only refetch what changed
uv run python -m rag.ingest --refresh-urls  # rewrite sources.json
uv run python -m rag.ingest --force-refetch # bypass ETag cache
uv run python -m rag.ingest --dry-run       # skip Pinecone upsert
```

If 1 of 3 documents fails its fetch / parse / embed / upsert cycle, the
others still complete and the CLI exits non-zero so a future cron / GitHub
Action surfaces the failure instead of swallowing it.

## Documents indexed

| `doc_id` | Title | Landing page |
|----------|-------|--------------|
| `tfl_business_plan` | TfL Business Plan | `tfl.gov.uk/.../business-plan` |
| `mts_2018` | Mayor's Transport Strategy 2018 | `london.gov.uk/.../mayors-transport-strategy-2018` |
| `tfl_annual_report` | TfL Annual Report and Statement of Accounts | `tfl.gov.uk/.../annual-report` |

Landing pages are the citation surface; resolved CDN URLs are not, because
TfL roll the URL stem yearly.

## Idempotency strategy

| Stage | Mechanism |
|-------|-----------|
| Fetch | `If-None-Match` + `If-Modified-Since` from `data/cache/sources_state.json` |
| Embed | OpenAI batch endpoint, retry on 429 |
| Upsert | Stable id `sha256("{resolved_url}::{chunk_index}")` |
| Rollover | Delete-namespace before re-ingest when `--refresh-urls` flips the URL |

## Pinecone index shape

```text
Index:        tfl-strategy-docs
Dimension:    1536
Metric:       cosine
Cloud:        AWS, us-east-1 (serverless)
Namespaces:   tfl_business_plan / mts_2018 / tfl_annual_report
Metadata:     doc_id, chunk_index, page, text
```

## Config

All settings ride on `BaseSettings` — env-driven, no CLI flags for static
config:

| Env var | Default |
|---------|---------|
| `OPENAI_API_KEY` | (required) |
| `PINECONE_API_KEY` | (required) |
| `PINECONE_INDEX` | `tfl-strategy-docs` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` |
| `RAG_SOURCES_PATH` | `src/rag/sources.json` |
| `RAG_CACHE_DIR` | `data/cache` |
| `RAG_LOCAL_PDF_DIR` | `data/strategy_docs` |

## Cost

A full re-embedding of all three PDFs runs at well under £0.20 one-time at
the current `text-embedding-3-small` price ($0.02 per 1M tokens).
**Conditional GETs and stable Pinecone IDs mean steady-state runs incur
near-zero embedding spend** — most weeks every doc returns 304 and the CLI
exits in under a second.

## Tests

28 unit tests with fakes for httpx / Docling / OpenAI / Pinecone:

| Module | Coverage |
|--------|----------|
| `sources.py` | landing-page resolver picks the right PDF URL via per-source allowlist |
| `fetch.py` | 304 short-circuit, 200 with body, ETag round-trip |
| `parse.py` | Docling output → chunks with stable text + page metadata |
| `embed.py` | Batch sizing, retry on 429, async ordering preserved |
| `upsert.py` | Id stability, namespace rollover, partial-failure handling |
| `ingest.py` | Orchestrator argument parsing, exit-non-zero on partial failure |
