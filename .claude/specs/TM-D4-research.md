# TM-D4 — Research (Phase 1)

Read-only exploration that frames the RAG ingestion WP. Captures the
state of the repo, the canonical URLs of the three TfL strategy PDFs,
the chunking and idempotency design, and the Pinecone index spec. No
code changes proposed here — see `TM-D4-plan.md` for the build plan.

## 1. Where TM-D4 sits in the codebase

- **PROGRESS.md row:** Phase 5, track `D-api-agent`, blocked by TM-000
  only (per Linear, no upstream WP needed). Sibling Phase-3 D-track WP
  TM-D2 is independent.
- **Linear issue:** `TM-17`. PR will close it.
- **No prior `src/rag/` directory.** `src/agent/{graph.py,observability.py}`
  are TM-D1 stubs — they only validate `LANGSMITH_*` env. The real
  agent (TM-D5) consumes the index this WP produces.
- **Tech-stack reminder (CLAUDE.md):** Docling 2.x for PDF parse,
  OpenAI `text-embedding-3-small` (1536 dim), Pinecone serverless,
  LlamaIndex permitted but skip if Docling alone suffices.
- **Lean discipline (CLAUDE.md Principle #1):** rule 4 (no factory
  without two consumers), rule 5 (no nested `BaseSettings` unless ≥15
  vars). RAG settings will sit in a single `Settings(BaseSettings)`
  with three fields plus a Pinecone index name and embedding model
  string — five env vars, well under the threshold.

## 2. Canonical PDF URLs (verified 2026-04-28)

Resolved live via WebFetch + `curl -I` (full HTTP HEAD response). Each
landing page is HTML; the direct PDFs sit on `content.tfl.gov.uk` (302
redirect from the `tfl.gov.uk/cdn/...` aliases) or
`www.london.gov.uk/sites/default/files/...`.

| name              | doc_id                 | landing_url                                                                                                | resolved_url (final after redirects)                                                                  | size   | last-modified                | etag                                       |
|-------------------|------------------------|------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|--------|------------------------------|---------------------------------------------|
| TfL Business Plan | `tfl_business_plan`    | `https://tfl.gov.uk/corporate/publications-and-reports/business-plan`                                      | `https://content.tfl.gov.uk/2026-business-plan-acc.pdf`                                                | 12.18 MB | Fri, 06 Feb 2026 13:33:35 GMT | `"26f28a9e4a7081b2be321dfad793bc98-2"`     |
| Mayor's Transport Strategy | `mts_2018`    | `https://www.london.gov.uk/programmes-strategies/transport/our-vision-transport/mayors-transport-strategy-2018` | `https://www.london.gov.uk/sites/default/files/mayors-transport-strategy-2018.pdf`                | 22.68 MB | Fri, 09 Sep 2022 19:48:36 GMT | `"631b9894-15a1d3b"`                        |
| TfL Annual Report | `tfl_annual_report`    | `https://tfl.gov.uk/corporate/publications-and-reports/annual-report`                                      | `https://content.tfl.gov.uk/tfl-annual-report-and-statement-of-accounts-2024-25.pdf`                  | 25.94 MB | Fri, 26 Sep 2025 12:42:16 GMT | `"cb73f493a2554cdbd378d3569dba7a53-4"`     |

**Note on the MTS landing page:** the briefing's URL
`https://www.london.gov.uk/programmes-strategies/transport/mayors-transport-strategy-2018`
returns 404. The current canonical landing is under
`/our-vision-transport/...`. Spec uses the corrected path.

### URL stability and resolution strategy

- **TfL URLs rotate annually.** The 2026 Business Plan replaces the
  2025 one at the same landing page; the URL stub embeds the year
  (`2026-business-plan-acc.pdf`). The Annual Report follows the same
  pattern (`tfl-annual-report-and-statement-of-accounts-2024-25.pdf`).
- **MTS URL is stable** (single document published 2018; not annually
  refreshed).
- **Resolution algorithm:** scrape the landing HTML for the first
  `<a href="...pdf">` whose URL stem matches a per-doc allowlist regex
  (e.g. `business-plan` for TfL Business Plan). Hosts can return
  relative URLs (`/cdn/static/cms/documents/...`); we resolve against
  the landing-page origin.
- **Fallback:** if the regex finds no match (TfL changes the link
  text), the resolver raises a clear error with the landing URL and
  the regex that failed; we never silently fall back to a stale URL.

### Conditional GET strategy

- Send `If-None-Match: <cached etag>` and `If-Modified-Since: <cached
  last-modified>` on the resolved URL.
- `200` → new content, write to `data/strategy_docs/<doc_id>.pdf`,
  update cache.
- `304` → unchanged, skip; orchestrator emits a `rag.fetch.unchanged`
  Logfire span.
- `404`/`410` → propagate as a hard error and abort the run; the
  upstream landing page gave us a stale `resolved_url` and we need to
  re-resolve from the landing page.

## 3. Chunking strategy

Docling 2.x ships its own chunker; LlamaIndex would add a layer with
no value here.

- **Parser:** `docling.document_converter.DocumentConverter().convert(path)`
  returns a `DoclingDocument`. Built-in OCR+layout pipeline handles
  the TfL PDFs without custom config.
- **Chunker:** `docling.chunking.HybridChunker(tokenizer=<openai>,
  max_tokens=512, merge_peers=True)`. The hybrid chunker first
  segments by document hierarchy (headings/sections/paragraphs) and
  then merges sibling chunks under the token cap, preserving section
  boundaries when possible. Output: an iterable of `DocChunk` objects
  with `text`, `meta` (`headings`, `doc_items`, page numbers via
  bounding-box prov data).
- **Token target:** 512 tokens with `merge_peers=True` is Docling's
  documented default for retrieval; it sits comfortably under
  `text-embedding-3-small`'s 8191-token input cap and gives ~10 chunks
  per page on dense reports — appropriate granularity for
  question-level retrieval.
- **Per-chunk metadata** (carried into Pinecone):
  - `doc_id`: stable string (`tfl_business_plan`, `mts_2018`,
    `tfl_annual_report`)
  - `doc_title`: human-readable
  - `resolved_url`: PDF URL at ingestion time (auditing)
  - `section_title`: first heading in the chunk's `meta.headings`
    (string; `""` if none)
  - `page_start`, `page_end`: int derived from `meta.doc_items[*].prov`
    bbox `page_no`; `None` if missing
  - `text`: chunk text (also stored as Pinecone vector value via the
    `metadata.text` convention used by LangChain/LlamaIndex retrievers
    for citation rendering — keeps TM-D5 free of a second SQL/JSON
    fetch step)

### Why not LlamaIndex

- Pinecone's Python client v5 has direct `index.upsert(vectors=[...])`.
- OpenAI's async client handles batched embeddings without a wrapper.
- Docling already exposes structured chunks with metadata.

Adding LlamaIndex would mean threading three abstractions (Document,
TextSplitter, VectorStore) for code that fits in ~100 lines of direct
Pydantic-validated logic. Defer LlamaIndex to TM-D5 (retrieval), where
the framework's reranking helpers earn their place.

## 4. Embedding strategy

- **Model:** `text-embedding-3-small`, 1536 dimensions. CLAUDE.md
  tech-stack and pyproject already pin OpenAI ≥1.54.
- **Batch size:** 100 inputs per request. The async OpenAI client
  awaits a single coroutine per batch.
- **Retry:** mirror `src/ingestion/tfl_client/retry.py` —
  exponential backoff on `openai.RateLimitError` (HTTP 429) and
  `openai.APIConnectionError` / `openai.APITimeoutError`. 5 attempts
  capped at 10 s. Fast-fail on `openai.AuthenticationError` (no key).
- **Concurrency:** 3 in-flight batches (`asyncio.Semaphore(3)`). With
  `n=100/batch`, each PDF fits in ≤25 batches — with concurrency 3, a
  full run is sub-minute.

## 5. Pinecone index spec and idempotency

- **Index name:** `tfl-strategy-docs` (overrideable via
  `PINECONE_INDEX`).
- **Dimensions:** 1536 (matches embedding model).
- **Metric:** `cosine` (OpenAI embeddings are unit-normalised; cosine
  = dot product up to scale and is the standard for `text-embedding-3-*`).
- **Capacity:** serverless — `cloud="aws"`, `region="us-east-1"` (the
  Pinecone serverless free-tier default and lowest-latency for
  US-region OpenAI).
- **Bootstrap:** ingestion creates the index if absent
  (`pc.create_index(name=..., dimension=1536, metric="cosine",
  spec=ServerlessSpec(...))`). Idempotent: `pc.list_indexes()` first.

### Vector id strategy

- **Id format per task brief:**
  `sha256(f"{resolved_url}::{chunk_index}").hexdigest()` — full 64-hex
  string. Stable for a given (URL, chunk_index) pair, so re-ingesting
  the same PDF version overwrites in place.
- **Namespace per doc_id:** `tfl_business_plan`, `mts_2018`,
  `tfl_annual_report`. Three namespaces in one index.
- **Stale-vector cleanup:** when a re-ingest fetches a *different*
  `resolved_url` for the same `doc_id` (year rolled over), delete the
  namespace before upserting:
  `index.delete(delete_all=True, namespace=doc_id)`. Pinecone
  serverless supports `delete_all=True` per-namespace on free tier.
- **Idempotency end-to-end:** `--force-refetch` re-downloads even on
  304; the deterministic id ensures no duplicates pile up.

## 6. Failure model and `--dry-run`

- **`--dry-run`** runs fetch + parse + chunk + embed and prints
  per-doc summary (`chunks=N`, `tokens≈N`, `vectors_to_upsert=N`)
  without calling `index.upsert`. Useful for the author to size the
  payload before the first prod run.
- **`--force-refetch`** ignores the cached ETag and downloads
  unconditionally. Useful when the cache is corrupt or when adding a
  new doc and we want to verify the discovery rule.
- **Missing `PINECONE_API_KEY`:** fail loud with a clear message and
  exit 2. Matches the briefing's hard rule "fail loud … never silently
  succeed".
- **Missing `OPENAI_API_KEY`:** same — exit 2.
- **Pinecone index missing and create fails:** propagate the SDK
  error; do not silently skip.

## 7. State at rest

| Path                                     | Status      | Contents                                                                                  |
|------------------------------------------|-------------|--------------------------------------------------------------------------------------------|
| `src/rag/sources.json`                   | committed   | List of `{name, doc_id, landing_url, resolved_url, discovery_regex}` — one entry per PDF. |
| `data/strategy_docs/<doc_id>.pdf`        | gitignored  | Last-fetched PDF bytes.                                                                    |
| `data/cache/sources_state.json`          | gitignored  | Per-`doc_id`: `{resolved_url, etag, last_modified, sha256, fetched_at}`.                  |

`resolved_url` is committed in `sources.json` so anyone cloning the
repo can reproduce; it gets refreshed when `--refresh-urls` is
supplied. ETag/Last-Modified live in `data/cache/` because they are
runtime state, not config (CLAUDE.md §"Pydantic usage conventions" —
config crosses git, state does not).

## 8. Test strategy

- **Unit (`tests/rag/`):**
  - `test_sources.py` — discovery regex parses representative TfL
    HTML snippets, including the rotating-year Business Plan link.
    Failure case: no PDF link found raises with a clear error.
  - `test_fetch.py` — `httpx.MockTransport`: 200 → write file +
    update cache; 304 → no write, log unchanged; 404 → raise.
    `--force-refetch` ignores cached headers.
  - `test_parse.py` — fake `DocumentConverter` returns a small
    `DoclingDocument` with two sections; assert chunk metadata
    (`doc_id`, `section_title`, page numbers).
  - `test_embed.py` — fake OpenAI client returns deterministic 1536
    -dim vectors per input; assert batch grouping and retry on a
    one-off `RateLimitError`.
  - `test_upsert.py` — fake Pinecone client; assert `delete(delete_all
    =True, namespace=doc_id)` is called when `resolved_url` changed,
    not called otherwise; assert `upsert(vectors=...,
    namespace=doc_id)` payload shape and id format.
  - `test_ingest_orchestrator.py` — wire all fakes; assert end-to-end
    flow under `--dry-run` (no upsert call) and under normal run
    (one upsert per non-empty doc).
- **Integration:** none on CI. Real Pinecone upsert is gated behind
  `PINECONE_API_KEY`; absence skips the integration test (mirrors
  `DATABASE_URL` gate in `tests/ingestion/integration/`).
- **Real PDF parse:** Docling is heavy; default suite uses fakes.
  A `pytest.mark.integration` test under `tests/rag/integration/`
  parses a tiny stub PDF (`tests/fixtures/rag/sample.pdf`, 1 page,
  committed once) — exercises the real Docling pipeline without
  hitting the 25 MB Annual Report. Skipped under default
  `pyproject.toml` `addopts = "-m 'not integration'"`.

## 9. Open questions to resolve in the plan

1. **Q1 — Sidecar split.** Commit `resolved_url` in
   `src/rag/sources.json`, ETag/Last-Modified/sha256 in
   `data/cache/sources_state.json`. Confirms the briefing's hint.
2. **Q2 — Discovery regex per doc.** Per-doc allowlist regex stored in
   `sources.json` (`discovery_regex` field). Resolver picks the first
   `<a href>` whose absolute URL matches. Avoids fragile string
   matching on link text.
3. **Q3 — Chunk size.** 512 tokens, `merge_peers=True`. Defaults to
   Docling's documented retrieval target. Open to revisiting in TM-D5
   based on retrieval quality.
4. **Q4 — Concurrency.** `asyncio.Semaphore(3)` for OpenAI batches.
   No concurrency between docs — three PDFs is small and serial keeps
   the trace timeline readable in Logfire/LangSmith.
5. **Q5 — Pinecone namespace per doc_id.** Yes — clean delete-by-namespace
   on year-roll, no metadata-filter-delete dependency (which Pinecone
   serverless free tier does not expose).
6. **Q6 — Index bootstrap.** Idempotent `create_index` on every run;
   `list_indexes()` short-circuits when present.
7. **Q7 — `--dry-run` vs `--force-refetch` interaction.**
   `--dry-run --force-refetch` re-downloads the PDF (testing fetch
   path) but stops before upsert. Documented in `--help`.
8. **Q8 — Logfire spans.** `rag.fetch`, `rag.parse`, `rag.embed`,
   `rag.upsert`, `rag.ingest.cycle` (top-level). `service_name =
   "tfl-monitor-rag-ingestion"`. Reuses `LOGFIRE_TOKEN` env (no new
   var).
9. **Q9 — `make check` impact.** `uv run task lint` and `uv run task
   test` already cover `src/`. No new Make target needed; ingestion
   runs via `uv run python -m rag.ingest`.
10. **Q10 — Bandit.** Subprocess and HTTP usage trigger no HIGH-severity
    findings on the planned code shape (no `shell=True`, no string
    interpolation in SQL, parameterised httpx calls only).

## 10. References

- CLAUDE.md §"Tech stack", §"Principle #1", §"Pydantic usage
  conventions", §"Observability architecture".
- AGENTS.md §1 (track inventory — `src/` is in scope).
- `pyproject.toml` — `pinecone>=5.0`, `docling>=2.0`, `openai>=1.54`,
  `httpx>=0.28`, `pydantic>=2.9`, `pydantic-settings>=2.6` already
  pinned. No new dependency.
- `src/ingestion/tfl_client/retry.py` — pattern for the OpenAI retry
  helper.
- `src/ingestion/observability.py` — pattern for the RAG Logfire
  helper.
- Docling docs (consulted at plan time):
  `https://github.com/DS4SD/docling`, chunking module:
  `docling.chunking.HybridChunker`.
- Pinecone Python client v5 docs:
  `https://docs.pinecone.io/reference/python-client`.
- Live HEAD probes captured 2026-04-28 in this WP's `curl -I`
  transcript (above table).
