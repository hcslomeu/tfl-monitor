# ADR 014: Decommission the warehouse — serve TfL live + RAG only

- Status: Accepted
- Date: 2026-05-28

## Context

The pipeline ingested TfL feeds through a Kafka/Redpanda broker into `raw.*`
landing tables, then dbt-modelled them into staging and marts. Two structural
problems made this untenable:

- **The warehouse fills the free tier and bricks the database.** The `raw.*`
  tables hoard TfL feed history that grows without bound, repeatedly outrunning
  the Supabase 500 MB free cap. Three successive Supabase projects were lost to
  disk-full failure modes — `pg_wal` crash-loops and OOM — each time the
  warehouse caught up with the cap. Plain `DELETE` never reclaims the space on a
  near-full instance, and recreating the project is the only reliable recovery.
- **There is no product reason to hoard live feeds.** TfL exposes a live API.
  The app's value is current network status plus a RAG chat over TfL strategy
  documents — not historical time-series analytics. Storing the feeds as history
  buys nothing the live API does not already serve on demand.

Redpanda Cloud's trial also expired on 2026-05-28, freezing ingestion
regardless. The streaming broker and the warehouse are both locked stack
choices, and this change drops `raw.*` DDL and the `tfl` dbt source under
`contracts/`, so it warrants an ADR and a `contract:`-prefixed PR.

## Decision

Turn the app into a **live TfL proxy + RAG chat**. Read through to the TfL API
on demand, keep the pgvector RAG store, and drop the warehouse entirely.

**Final Postgres surface** — every object is static or bounded; nothing grows
with feed volume:

| Object | Purpose | Source of truth |
|---|---|---|
| pgvector store (`<schema>.data_<table>`) | RAG retrieval | `rag.ingest` |
| `analytics.chat_messages` | chat memory / `/history` | app writes |
| `ref.lines` | line metadata lookup | dbt seed |
| `ref.stations` | station lookup | dbt seed |
| `analytics.dim_stations` | NaPTAN→name fast path (live fallback) | dbt model from `ref.stations` |

**Read-live rewrites** (via the existing `TflClient`):

- `GET /api/v1/status/live` → TfL `/Line/Mode/{modes}/Status`.
- `GET /api/v1/disruptions/recent` → TfL `/Line/Mode/{modes}/Status?detail=true`,
  walking `Line → lineStatuses[] → disruption`. **Not** `/Disruption`: the
  free-tier `/Disruption` endpoint returns empty `affectedRoutes`/`affectedStops`,
  whereas `?detail=true` carries the populated fan-out (see ADR 007).
- Agent tools `query_tube_status` and `query_recent_disruptions` hit the same
  live calls. Every `TflClient` call inside a `@tool` body is wrapped in
  `try/except` returning a friendly string — LangGraph re-raises non-`ToolException`
  errors and would otherwise crash the chat stream (see ADR 010).

**Removed**: the `raw.*` tables and their indexes; the `tfl` dbt source; the
Kafka/Redpanda broker plus all producers, consumers, and `aiokafka`; the
`/reliability/{line_id}`, `/status/history`, and `/bus/{stop_id}/punctuality`
endpoints with their `db.py` SQL and fetch functions; the `query_line_reliability`
and `query_bus_punctuality` agent tools; the staging models and the reliability,
bus, and disruptions marts; `src/api/maintenance.py` and the retention cron.

**Kept**: `TflClient` + `normalise` + `retry`; the RAG package and retriever;
chat persistence (`InMemorySaver`, `append_message`/`fetch_history`, the
`/chat/*` routes); the `stations` resolver; and the journey, arrivals, and
search agent tools. The dbt project keeps the seeds and the `dim_stations`
model only.

## Consequences

- The database can no longer fill from feed history. The disk-full brick class
  of incident — the single largest source of production outages in this
  project — is structurally eliminated.
- No broker to operate, secure, or pay for. The Lightsail box drops the
  producer, consumer, and Redpanda processes, freeing RAM on the shared 2 GB
  host.
- Live calls add latency versus a warehouse read. Acceptable at portfolio
  scale; a short TTL cache is deferred (YAGNI) and revisited only if TfL
  rate-limits bite.
- `dim_stations` is still dbt-built, so deploy runs one seed + `dim_stations`
  build instead of the `*/15` cron.
- Historical analytics (reliability trends, bus punctuality) are gone. The live
  proxy + RAG is the portfolio story; a bounded-retention warehouse can return
  under a future ADR if it is ever justified.
- **Supersedes ADR 001** (Redpanda over Apache Kafka) — there is no broker — and
  **ADR 005** (raw-table defaults) — there are no `raw.*` tables. It also
  obsoletes the direct-ingest daemon drafted as ADR 012 in the canceled TM-32,
  which still wrote `raw.*` history.
- The CLAUDE.md tech-stack table drops the streaming-broker and Kafka rows
  (broker: none); `docs/stack.md` and `docs/adrs.md` are updated to match.
