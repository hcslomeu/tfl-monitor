# TM-35 — Sync mkdocs site with live-proxy architecture (ADR 014)

Docs-only sweep. The published site under `docs/` still documents the streaming
pipeline removed by ADR 014 (Kafka/Redpanda broker, producers/consumers, the
`raw.*` warehouse with staging/marts, and the `/reliability`, `/status/history`,
`/bus` endpoints). TM-34 already fixed `docs/stack.md`, `docs/adrs.md`, and the
package READMEs; this WP closes the rest.

## Source of truth

ADR 014 (`.claude/adrs/014-decommission-warehouse-live-proxy.md`, supersedes 001
+ 005). The app is a **live TfL proxy + RAG chat**:

- `GET /api/v1/status/live` → TfL `/Line/Mode/{modes}/Status` via `TflClient`.
- `GET /api/v1/disruptions/recent` → TfL `/Line/Mode/{modes}/Status?detail=true`.
- Chat agent tools: `query_tube_status`, `query_recent_disruptions`,
  `search_tfl_docs` (RAG), `plan_journey_tool`, `get_arrivals_tool`, plus the
  `stations` resolver / search. **No** `query_line_reliability`,
  `query_bus_punctuality`.
- Postgres holds only: pgvector RAG store, `analytics.chat_messages`,
  `ref.lines`, `ref.stations`, `analytics.dim_stations`. No `raw.*`, no
  staging/marts. dbt = seeds + `dim_stations` model, built one-shot on deploy.
- No broker. RAG ingest is host cron (not Airflow — removed ADR 008).

## Decisions (author-confirmed)

1. Rewrite the two dead pages in-place (keep URLs + nav slots):
   - `pipelines/ingestion.md` "Streaming ingestion" → "Live TfL proxy".
   - `pipelines/warehouse.md` "dbt warehouse" → "Reference data" (seeds +
     `dim_stations`).
2. Tracked as its own Linear issue TM-35; standalone docs-only PR.

## Files

Rewrite: `architecture.md`, `pipelines/ingestion.md`, `pipelines/warehouse.md`.
Surgical: `index.md`, `engineering.md`, `observability.md`, `roadmap.md`,
`glossary.md`, `deployment.md`, `pipelines/{index,agent,api,rag,frontend}.md`,
`mkdocs.yml` (`site_description` + nav labels).
Leave: `stack.md`, `adrs.md` (already correct); `docs/superpowers/*`
(point-in-time design docs, outside nav).

## Acceptance

- `uv run task docs-build` (`mkdocs build --strict`) passes.
- No residual reference to Kafka/Redpanda/broker/producer/consumer/`raw.*`/
  staging/marts or the `/reliability`//`/status/history`//`/bus` endpoints in any
  nav page (grep clean).
- `make check` green; PR opened referencing TM-35.

## What we're NOT doing

- No README / demo video (that stays TM-F1).
- No nav-page deletions or new pages.
- No code, contract, or dbt changes — docs only.
- No edits to `docs/superpowers/*` historical artifacts.
