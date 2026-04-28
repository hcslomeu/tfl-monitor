# PROGRESS

Current state of work packages. Update the status column as WPs land.

| Phase | WP | Title | Track | Status | Notes |
|---|---|---|---|---|---|
| 0 | TM-000 | Contracts and scaffold | — | ✅ 2026-04-22 | Scaffold, contracts, tier-1/tier-2 schemas, fixtures fetched |
| 1 | TM-A1 | Docker Compose + Postgres + Redpanda + Airflow | A-infra | ✅ 2026-04-23 | Round 3 follow-up applied: pgcrypto + DB-side defaults on raw tables; integration smoke test gated on `DATABASE_URL` |
| 1 | TM-B1 | Async TfL client + fixtures | B-ingestion | ✅ 2026-04-26 | Async `httpx` client with hand-rolled retry (429/5xx/timeout), tier-1 → tier-2 normalisation (line-status, arrivals, disruptions with synthetic SHA-256 IDs), `app_key` redacted in Logfire spans, fixtures committed under `tests/fixtures/tfl/`. |
| 2 | TM-C1 | dbt scaffold | C-dbt | ✅ 2026-04-23 | Acceptance criteria absorbed by TM-000: `dbt/sources/tfl.yml` mirrors `contracts/dbt_sources.yml` (CI-enforced), `dbt-parse` green, `.gitkeep`s pin empty model dirs. |
| 2 | TM-D1 | FastAPI skeleton + Logfire wiring | D-api-agent | ✅ 2026-04-26 | Locked 501 stubs with parametrised tests, added bidirectional OpenAPI drift test, extended CORS allow-list with `https://tfl-monitor.vercel.app` (G1 + G2 + G4 from research). |
| 3 | TM-B2 | `line-status` producer | B-ingestion | ✅ 2026-04-27 | Async daemon (`LineStatusProducer.run_forever`), 30s fixed-rate cadence, `KafkaEventProducer` wrapper around `AIOKafkaProducer` (idempotent, `acks="all"`, partition key=`line_id`), `event_type="line-status.snapshot"`, UUIDv4 `event_id`. Compose service `tfl-line-status-producer` (profile `ingest`) + `redpanda-init` (profile `init`) + `src/ingestion/Dockerfile`. 16 unit tests + 1 integration smoke. |
| 3 | TM-B3 | `line-status` consumer | B-ingestion | ✅ 2026-04-28 | Async `LineStatusConsumer.run_forever` reads `line-status` topic with `group_id="tfl-monitor-line-status-writer"`, `auto_offset_reset="earliest"`, `enable_auto_commit=False`. `KafkaEventConsumer` wrapper mirrors TM-B2 producer. `RawLineStatusWriter` over single async psycopg connection with `INSERT … ON CONFLICT (event_id) DO NOTHING` for idempotency, reconnect-on-`OperationalError`. Failure isolation: poison pill = skip+commit; transient DB = reconnect+replay; unknown = log+replay. Lag traced on every `kafka.consume` span, refreshed every 50 msgs / 30 s. Compose service `tfl-line-status-consumer` (profile `ingest`) + `consume-line-status` task/Makefile. Observability helper `src/ingestion/observability.py` extracted (producer migrated). 21 unit tests + 1 integration smoke. |
| 3 | TM-C2 | dbt staging + first mart | C-dbt | ✅ 2026-04-28 | `stg_line_status` (incremental `merge` on `event_id`, JSONB unnested into typed columns, defensive `row_number()` dedup, `on_schema_change=fail`); `mart_tube_reliability_daily` at grain `(line_id, calendar_date UTC, status_severity)` with `snapshot_count`, `first/last_observed_at`, `minutes_observed_estimate` (1 snapshot ≈ 30 s, anchored on `LINE_STATUS_POLL_PERIOD_SECONDS`). Generic + 2 singular tests under `dbt/tests/`. `model-paths` extended to `["models", "sources"]` so dbt resolves the source YAML. No `dbt_utils` dependency. |
| 3 | TM-D2 | Wire endpoints to Postgres | D-api-agent | ⬜ | |
| 3 | TM-E1a | Next.js scaffold + shadcn + Network Now (mocked) | E-frontend | ✅ 2026-04-28 | scaffold + mocked data; real wiring in E1b post-D2. Vitest+RTL added (6 tests), `make check` chains `pnpm --dir web test`. |
| 3 | TM-E1b | Network Now wired to real `/status/live` | E-frontend | ⬜ | Swap `lib/api/status-live.ts` body for `apiFetch<LineStatus[]>(...)` once TM-D2 lands. |
| 4 | TM-B4 | arrivals + disruptions topics | B-ingestion | ✅ 2026-04-28 | `ArrivalsProducer` polls 5 NaPTAN hubs every 30s (partition key `station_id`, `event_type="arrivals.snapshot"`); `DisruptionsProducer` polls 4 modes every 300s (partition key `disruption_id`, `event_type="disruptions.snapshot"`). Consumer + writer generalised: `RawEventConsumer[E]` + `RawEventWriter(table)` with allow-listed table names; line-status migrated in same PR (Logfire namespace `ingestion.line_status.*` preserved via `log_namespace` override). `redpanda-init` creates all three topics; four new Compose services on profile `ingest`. 27 new unit tests (arrivals + disruptions producers, parametrised consumer × 3 topics, 3 namespace whitebox cases) + smoke parametrised across topics. |
| 4 | TM-C3 | Remaining marts + tests + exposures | C-dbt | ✅ 2026-04-28 | `stg_arrivals` + `stg_disruptions` (incremental `merge`, 5 min lookback, DESC dedup); `mart_tube_reliability_daily_summary` at `(line_id, calendar_date)` with `pct_good_service` + gaps-and-islands `longest_disruption_window_minutes`; `mart_disruptions_daily` at `(calendar_date, line_id)` with affected_routes JSONB fan-out + `distinct_categories` + `max_severity`; `mart_bus_metrics_daily` at `(calendar_date, line_id, station_id)` filtering bus lines via `source('tfl', 'lines')` (returns 0 rows until TM-A2 populates `ref.lines`). 5 singular tests under `dbt/tests/` (pct bound, three composite-grain uniqueness, disruption category enum). 5 dbt exposures wiring marts to the warehouse-backed API endpoints. Marts run empty until TM-B4 lands; contracts frozen. |
| 4 | TM-D3 | Remaining endpoints | D-api-agent | ⬜ | |
| 4 | TM-E2 | Disruption Log view | E-frontend | ⬜ | |
| 5 | TM-A2 | Airflow DAGs | A-infra | ⬜ | |
| 5 | TM-D4 | RAG ingestion: Docling → Pinecone | D-api-agent | ✅ 2026-04-28 | `src/rag/` package: `sources.py` resolves the direct-PDF URL on each landing page (3 TfL strategy docs) via per-source allowlist regex; `fetch.py` does conditional GET (`If-None-Match` + `If-Modified-Since`) into `data/strategy_docs/`; `parse.py` wraps Docling 2.x `DocumentConverter` + `HybridChunker` (library defaults; the Docling 2.x constructor derives chunk size from its tokenizer); `embed.py` async-batches OpenAI `text-embedding-3-small` (100/req, retry on 429); `upsert.py` Pinecone serverless `tfl-strategy-docs` (1536 dim, cosine, AWS us-east-1), one namespace per `doc_id`, stable id = `sha256("{resolved_url}::{chunk_index}")`, delete-namespace-on-rollover idempotency; `ingest.py` orchestrator with `--refresh-urls`, `--force-refetch`, `--dry-run` flags, fail-loud on missing `PINECONE_API_KEY`/`OPENAI_API_KEY`. 28 unit tests with fakes for httpx/Docling/OpenAI/Pinecone. |
| 6 | TM-D5 | LangGraph agent (SQL + RAG + Pydantic AI) | D-api-agent | ⬜ | |
| 6 | TM-E3 | Chat view with SSE | E-frontend | ⬜ | |
| 7 | TM-A3 | Supabase provisioning | A-infra | ⬜ | |
| 7 | TM-A4 | Redpanda Cloud | A-infra | ⬜ | |
| 7 | TM-A5 | Railway deploy (Airflow + API + agent + workers) | A-infra | ⬜ | |
| 7 | TM-E4 | Vercel deploy | E-frontend | ⬜ | |
| 7 | TM-F1 | README polish + demo video + live URL | F-polish | ⬜ | |

## TM-C1 notes

- Every functional acceptance criterion declared in `SETUP.md` §7.3 for
  TM-C1 was already satisfied by the TM-000 scaffold (dbt project,
  profiles, sources mirror, CI diff gate, `dbt-parse` task). This WP
  closes as a zero-code PR after verifying the CI diff + parse pass;
  see `.claude/specs/TM-C1-{research,plan}.md`.

## TM-000 notes

Mid-execution deviations, captured as ADRs or inline footnotes:

- `[tool.uv.scripts]` in the original spec is not a real uv feature;
  replaced by `taskipy` in `[tool.taskipy.tasks]` with a slim Makefile
  for system orchestration.
- Next.js generator produced v16.2.4 (spec locked at 15); kept v16
  because current `create-next-app` defaults to it and v16 is
  backward-compatible for the app-router scaffold used here. Tech-stack
  table in ARCHITECTURE.md and `CLAUDE.md` tech-stack list updated to
  match. A formal ADR will be added if issues surface in TM-E1+.
- shadcn CLI flow changed: `--base=radix --preset=nova` matches the
  legacy "Default / Slate / CSS variables=Yes" intent and avoids
  interactive prompts.
- Contracts split into two tiers: tier-1 `tfl_api` for raw TfL
  responses (camelCase, optional-heavy) and tier-2 Kafka events
  (snake_case, frozen, per spec §5.1). See ADR 002.
