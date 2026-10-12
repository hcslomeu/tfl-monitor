# Roadmap

The project is built as **work packages** (WPs), grouped into parallel tracks
so at most two agents can collide-free at any time.

## Track structure

| Track | Owner directories | Purpose |
|-------|------------------|---------|
| **A: infra** | `vercel.json`, `scripts/`, `.github/` | CI and Vercel deploy config |
| **B: ingestion** | `src/ingestion/tfl_client/` | Async TfL client (read-through) |
| **D: api-agent** | `src/api/` | FastAPI + LangGraph agent |
| **E: frontend** | `web/` | Next.js dashboard |
| **F: polish** | top-level docs, `README.md` | Demo, video, polish |

Track **C** (dbt) ended when ADR 015 removed the dbt project.

## Status

```mermaid
gantt
    dateFormat  YYYY-MM-DD
    title       tfl-monitor delivery timeline (✅ complete · 🚧 next up)
    section Foundations
    TM-000 Contracts + scaffold        :done, 2026-04-22, 1d
    TM-B1 TfL client + fixtures        :done, 2026-04-26, 1d
    TM-D1 FastAPI skeleton             :done, 2026-04-26, 1d
    section API + RAG + agent
    TM-D4 RAG ingestion                :done, 2026-04-28, 1d
    TM-D5 LangGraph agent              :done, 2026-04-29, 1d
    TM-32 Bedrock + pgvector cutover   :done, 2026-05-27, 1d
    section Frontend
    TM-E5 Dashboard one-pager          :done, 2026-05-12, 1d
    TM-30 Journey + arrivals tools     :done, 2026-05-27, 1d
    TM-33 Journey/arrivals chat cards  :done, 2026-05-28, 1d
    section Deploy
    TM-A5 Shared Lightsail + Bedrock   :done, 2026-05-19, 1d
    TM-E4 Vercel deploy                :done, 2026-05-13, 1d
    section Decommission + polish
    TM-34 Warehouse → live proxy       :done, 2026-05-28, 1d
    TM-35 Docs sync (live proxy)       :done, 2026-05-29, 1d
    section Vercel
    TM-36 Stateless API on Vercel      :active, 2026-10-12, 1d
    TM-F1 README polish + demo         :2026-10-13, 2d
```

## WP ledger

Source of truth: [`PROGRESS.md`](https://github.com/hcslomeu/tfl-monitor/blob/main/PROGRESS.md).
The highlights below are the delivery history; rows for RAG, Bedrock, and
Lightsail describe work later removed by ADR 015. The full per-WP notes live in
`PROGRESS.md`.

| Phase | WP | Title | Status |
|-------|----|-------|--------|
| 0 | TM-000 | Contracts + scaffold | ✅ |
| 1 | TM-B1 | Async TfL client + fixtures | ✅ |
| 2 | TM-D1 | FastAPI skeleton + Logfire | ✅ |
| 5 | TM-D4 | RAG ingestion (later migrated to PyMuPDF + Bedrock + pgvector) | ✅ removed in ADR 015 |
| 6 | TM-D5 | LangGraph agent (SQL + RAG + Pydantic AI) | ✅ |
| 7 | TM-E5 | Dashboard one-pager + chat | ✅ |
| 7 | TM-A5 | Shared Lightsail + Bedrock deploy | ✅ removed in ADR 015 |
| 7 | TM-E4 | Vercel deploy | ✅ |
| 7 | TM-29 | Station resolver + disruption enrichment | ✅ |
| 7 | TM-30 | Journey + arrivals agent tools | ✅ |
| 7 | TM-32 | RAG migration: Bedrock + pgvector | ✅ removed in ADR 015 |
| 7 | TM-33 | Journey/arrivals chat cards (SSE frames) | ✅ |
| 7 | TM-34 | Decommission warehouse → live TfL proxy + RAG | ✅ |
| 7 | TM-35 | Docs sync: mkdocs to live-proxy architecture | ✅ |
| 7 | TM-36 | Move API to Vercel; drop RAG, Postgres, Bedrock (ADR 015) | 🚧 |
| 7 | TM-F1 | README polish + demo video + live URL | ⬜ |

!!! note "Superseded WPs"
    Earlier streaming + warehouse WPs (line-status / arrivals / disruptions
    producers + consumers, the `raw.*` → staging → marts dbt models, and the
    reliability / bus endpoints) shipped and were later **removed by ADR 014**.
    The Airflow DAGs (TM-A2) were removed by ADR 008, and Docling/OpenAI/Pinecone
    (TM-D4) were replaced in TM-32. ADR 015 (TM-36) then removed the RAG
    pipeline (TM-D4, TM-32), the Pydantic AI extractor, Postgres and dbt, AWS
    Bedrock, and the shared Lightsail deploy (TM-A5). They remain in git
    history.

## How a WP closes

Every WP runs through this checklist before being marked `✅`:

- [x] All acceptance criteria from the spec met
- [x] `uv run task lint` (Ruff + Mypy strict) passes
- [x] `uv run task test` (Pytest) passes
- [x] `make check` (Python + TS gates chained) passes end-to-end
- [x] `PROGRESS.md` updated with completion date and notes
- [x] Linear issue moved to `Done`
- [x] PR opened, referencing the Linear issue, body in English
