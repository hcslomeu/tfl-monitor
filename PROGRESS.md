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
| 3 | TM-C2 | dbt staging + first mart | C-dbt | ⬜ | |
| 3 | TM-D2 | Wire endpoints to Postgres | D-api-agent | ⬜ | |
| 3 | TM-E1 | Next.js + claude.design + Network Now | E-frontend | ⬜ | |
| 4 | TM-B4 | arrivals + disruptions topics | B-ingestion | ⬜ | |
| 4 | TM-C3 | Remaining marts + tests + exposures | C-dbt | ⬜ | |
| 4 | TM-D3 | Remaining endpoints | D-api-agent | ⬜ | |
| 4 | TM-E2 | Disruption Log view | E-frontend | ⬜ | |
| 5 | TM-A2 | Airflow DAGs | A-infra | ⬜ | |
| 5 | TM-D4 | RAG ingestion: Docling → Pinecone | D-api-agent | ⬜ | |
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
