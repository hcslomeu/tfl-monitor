# TM-34 — Decommission ingestion + warehouse; serve TfL live + RAG only

Supersedes TM-32 ("remove Kafka broker, keep direct-ingest daemon" —
`TM-32-remove-kafka-plan.md`, ADR 012). That plan still wrote `raw.*`
history. This plan removes the history hoard entirely. TM-32 is canceled;
branch `feature/TM-32-remove-kafka` is abandoned.

## Why

The Supabase Postgres must hold **only** what is essential to run the app
plus the pgvector RAG store. TfL exposes a live API, so there is no reason
to hoard its feeds as time-series history. Every disk-full incident that
bricked Supabase v1 -> v2 -> v3 (pg_wal crash-loops, OOM) was caused by
`raw.*` accumulation outrunning the free tier. Redpanda Cloud's trial also
expired 2026-05-28, freezing ingestion. We turn the app into a **live TfL
proxy + RAG chat**: read-through to the TfL API on demand, keep the vector
store, drop the warehouse.

This is a stack-table change -> **ADR 014** (supersedes ADR 001 Redpanda and
ADR 012 direct-ingest). It touches `contracts/` (drops `raw.*` DDL and the
`tfl` dbt source) -> PR title prefix `contract:`.

## Scope decisions (confirmed with author)

1. Keep a minimal static cache: `ref.lines`, `ref.stations`,
   `analytics.dim_stations` survive (tiny, static, back station-name
   resolution; `resolve_naptans` already has a live TfL fallback on miss).
2. Drop the bus-punctuality feature (no TfL live equivalent; warehouse-only).
3. Keep a lean dbt: seeds (`ref.lines`, `ref.stations`) + the `dim_stations`
   model only. Remove all staging + marts.
4. One WP (TM-32 expanded). Kafka removal is the first implementation phase.

## Final Postgres surface (everything else removed)

| Object | Purpose | Source of truth |
|---|---|---|
| pgvector store (`<schema>.data_<table>`, env-configured) | RAG | `rag.ingest` |
| `analytics.chat_messages` | chat memory / `/history` | app writes |
| `ref.lines` | line metadata lookup | dbt seed |
| `ref.stations` | station lookup | dbt seed |
| `analytics.dim_stations` | naptan->name fast path (live fallback) | dbt model from `ref.stations` |

Nothing in this set grows unbounded.

## Rewrite-live (read TfL on demand via `TflClient`)

- `GET /api/v1/status/live` -> TfL `/Line/Mode/{modes}/Status` (current state).
- `GET /api/v1/disruptions/recent` -> TfL `/Line/Mode/{modes}/Status?detail=true`,
  walking `Line -> lineStatuses[] -> disruption`. **NOT** `/Disruption`
  (napkin Domain #2: the free-tier `/Disruption` returns empty
  `affectedRoutes`/`affectedStops`). Reuse `tfl_client.normalise` logic that
  already builds this shape (PR #96).
- Agent tools `query_tube_status` and `query_recent_disruptions` -> same live
  calls. Wrap every `TflClient` call inside a `@tool` body in `try/except`
  returning a friendly string (napkin Domain #12: LangGraph re-raises
  non-`ToolException` and crashes the stream otherwise).

## Remove

- **DB / contracts:** `raw.line_status`, `raw.arrivals`, `raw.disruptions`
  (`contracts/sql/001`), their indexes (`contracts/sql/003`). Drop the `tfl`
  dbt source in `contracts/dbt_sources.yml` (re-sync mirror via
  `make sync-dbt-sources`; napkin Domain #11).
- **Ingestion:** `src/ingestion/producers/*`, `src/ingestion/consumers/*`,
  `src/ingestion/kafka_config.py`, `run_producers`, `run_consumers`. **Keep**
  `src/ingestion/tfl_client/*` and `observability.py`.
- **Kafka/Redpanda:** Redpanda + console + init + all producer/consumer
  services and `redpanda-data` volume in `docker-compose.yml` and
  `infra/docker-compose.prod.yml`; `KAFKA_*` env; `aiokafka` dependency;
  pure-Kafka tests.
- **Endpoints:** `/api/v1/reliability/{line_id}`, `/api/v1/status/history`,
  `/api/v1/bus/{stop_id}/punctuality`.
- **db.py:** `LINE_STATUS_SQL`, `LINE_STATUS_HISTORY_SQL`, `RELIABILITY_SQL`
  (+ severity), `DISRUPTIONS_SQL`, `BUS_PUNCTUALITY_SQL`; functions
  `fetch_live_status`, `fetch_recent_disruptions`, `fetch_reliability`,
  `fetch_bus_punctuality`. **Keep** `append_message`, `fetch_history`.
- **Agent tools:** `query_line_reliability`, `query_bus_punctuality` (+ their
  prompt lines + toolset entries).
- **dbt:** `models/staging/*`, reliability + bus + disruptions marts. **Keep**
  seeds + `dim_stations`.
- **Maintenance:** `src/api/maintenance.py`, `scripts/cron-retention.sh`, the
  retention crontab entry; `scripts/cron-dbt-run.sh` becomes a one-shot
  seed+`dim_stations` build (no `*/15` cron).

## Keep (unchanged)

`TflClient` + `normalise` + `retry`; RAG (`src/rag/*`, `src/api/agent/rag.py`);
chat (`InMemorySaver`, `append_message`/`fetch_history`, `/chat/stream`,
`/chat/{thread_id}/history`); stations resolver (`src/api/stations.py`);
journey/arrivals/search agent tools.

## Implementation phases (test after each; stop if reality diverges)

- **P0 — ADR + docs.** Write ADR 014. Update CLAUDE.md stack table (remove
  Redpanda/Kafka rows; broker = none), `docs/stack.md`, `docs/adrs.md`,
  `PROGRESS.md`, `.claude/current-wp.md`.
- **P1 — API live.** Rewrite `status/live` + `disruptions/recent` live; remove
  reliability/history/bus endpoints and their `db.py` SQL/functions. Unit
  tests mock `TflClient`; update/replace endpoint tests.
- **P2 — Agent tools.** Rewrite `query_tube_status` + `query_recent_disruptions`
  live (try/except wrap); remove reliability + bus tools; update `prompts.py`
  + toolset. Tests.
- **P3 — Ingestion cull.** Delete producers/consumers/kafka_config; drop
  `aiokafka`; delete Kafka tests; keep `tfl_client`. `uv lock`.
- **P4 — Compose.** Remove Redpanda + ingestion services + `KAFKA_*` from both
  compose files.
- **P5 — dbt + contracts.** Remove staging + marts; keep seeds + `dim_stations`;
  drop `raw.*` DDL (`contracts/sql/001`,`003`) and the `tfl` source; re-sync
  the dbt sources mirror.
- **P6 — Maintenance.** Delete `maintenance.py` + retention cron + tests;
  reduce dbt cron to one-shot build.
- **P7 — Frontend.** Regenerate `web/lib/types.ts` from the shrunken OpenAPI;
  confirm no component referenced the dropped endpoints (grep already shows
  none); `pnpm --dir web lint && test`.
- **P8 — Verify + deploy.** Gate + live smokes + deploy + prod smoke.

## Success criteria

**Automated**
- `uv run task lint && uv run task test && uv run bandit -r src --severity-level high` green.
- `uv run task dbt-parse` green with seeds + `dim_stations` only.
- `make check` green end-to-end.
- `grep -ri "kafka\|redpanda\|aiokafka" src docker-compose*.yml infra` returns
  nothing (outside ADR history).
- `grep -rn "raw\.\(line_status\|arrivals\|disruptions\)" src dbt contracts`
  returns nothing.

**Manual (live)**
- `curl /api/v1/status/live` returns live TfL line states (not a DB snapshot).
- `curl /api/v1/disruptions/recent` returns populated `affected_routes`/
  `affected_stops` from `/Status?detail=true`.
- Chat answers: tube status, recent disruptions, a journey, arrivals, and a
  RAG doc question — end to end against prod.
- Dashboard renders the line grid + chat with no console errors.
- Prod DB contains only the five KEEP objects; box RAM lower; no Redpanda
  process; `/health` 200 from the workstation (napkin Exec #10).

## What we are NOT doing

- Not touching the RAG parse/ingest path (PR #127 owns PyMuPDF; this WP keeps
  RAG as-is).
- Not removing chat persistence, `dim_stations`, `ref.*`, or `TflClient`.
- Not reintroducing a broker, nor adding request caching for TfL calls yet
  (YAGNI; revisit only if rate limits bite).
- Not adding new features or endpoints beyond the live rewrites.

## Risks / notes

- Live calls add latency vs a DB read; acceptable for a portfolio app at this
  scale. Add a short TTL cache later only if TfL rate-limits.
- `dim_stations` is still built by dbt -> one dbt seed+run must run on deploy
  (no `*/15` cron).
- Sequencing vs PR #127: this branch is cut from `main` and does not touch RAG
  files, so overlap is minimal. If PR #127 merges first, rebase; otherwise the
  two merge independently.
