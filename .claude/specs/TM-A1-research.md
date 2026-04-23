# TM-A1 — Research (Phase 1)

## Objective recap

Bring up all local services via `docker compose` with healthchecks and verify
they satisfy the TM-A1 acceptance criteria + Round 3 follow-up from PR #25.

## What already exists (inherited from TM-000)

- `docker-compose.yml` at repo root declares:
  - `postgres` (Postgres 16) — port 5432, volume `postgres-data`, SQL init
    files mounted read-only from `./contracts/sql`, healthcheck via
    `pg_isready`, scram-sha-256 auth.
  - `redpanda` (redpandadata/redpanda:v24.2.7) — external listener 19092,
    volume `redpanda-data`, healthcheck via `rpk cluster info`.
  - `redpanda-console` (redpandadata/console:v2.7.2) — guarded by Compose
    profile `ui` (not started by default).
  - `airflow-init`, `airflow-webserver`, `airflow-scheduler` (built from
    `./airflow/Dockerfile = apache/airflow:2.10.3`) — LocalExecutor, metadata
    in the same Postgres (isolation deferred to TM-A3 per ADR 003 pending),
    webserver on port 8082 → 8080.
  - `minio` (minio/minio:RELEASE.2024-10-29T16-01-48Z) — ports 9000 + 9001,
    volume `minio-data`, healthcheck via `/minio/health/live`.
- `Makefile` targets present: `bootstrap`, `up`, `down`, `clean`, `check`,
  `seed`, `openapi-ts`, `sync-dbt-sources`.
- `contracts/sql/001_raw_tables.sql` creates `raw.line_status`,
  `raw.arrivals`, `raw.disruptions` — all with `event_id UUID PRIMARY KEY`
  and `ingested_at TIMESTAMPTZ NOT NULL`, **no DB-side defaults**.
- `contracts/sql/002_reference_tables.sql` creates `ref.lines`,
  `ref.stations` with `loaded_at DEFAULT NOW()`.
- `contracts/sql/003_indexes.sql` adds BTREE+GIN per raw table.

## What is missing

1. **DB-side defaults on raw tables** (Round 3 follow-up on TM-3):
   - Producers currently must supply `event_id` and `ingested_at`. Ad-hoc
     inserts and backfills break.
   - Add `CREATE EXTENSION IF NOT EXISTS pgcrypto;` (for `gen_random_uuid()`)
     ahead of the raw DDL.
   - Add `DEFAULT gen_random_uuid()` on `event_id` and `DEFAULT now()` on
     `ingested_at` on all three raw tables.
   - `NOT NULL` guarantees stay — defaults strengthen, they do not weaken.
2. **End-to-end boot validation** — the author has not yet run
   `docker compose up` against the scaffold. Need to confirm healthchecks
   reach `healthy` and the init SQL runs cleanly.
3. **Lightweight smoke test** — nothing today asserts the schemas and tables
   exist after Postgres starts. A small integration test (pytest, skipped
   when `DATABASE_URL` absent) would catch init regressions in CI later.

## What is explicitly out of scope

- Airflow metadata DB isolation → deferred to TM-A3 / ADR 003 (Phase 7).
- DAGs → TM-A2 (Phase 5).
- Seed loader → TM-B1+ populates fixtures.
- Supabase / Redpanda Cloud provisioning → Phase 7 WPs.

## Open questions (none blocking)

- Smoke test format: stand-alone pytest marker, or leave validation to manual
  `make up` + `docker compose ps`? Recommendation: single pytest with
  `pytest.importorskip("psycopg")` + env-var gate, runs only when explicitly
  asked — avoids needing Docker in CI.

## Success criteria (from TM-3 + Round 3 comment)

- [ ] `docker compose up -d` boots Postgres, Redpanda, Airflow (init →
  webserver + scheduler), MinIO. All report `healthy` within start periods.
- [ ] `contracts/sql/*` executes without error on first Postgres boot.
- [ ] `raw.*` tables have `DEFAULT now()` on `ingested_at` and
  `DEFAULT gen_random_uuid()` on `event_id`, plus `NOT NULL`.
- [ ] `make down` stops everything cleanly.
- [ ] `make clean` drops volumes (destructive, documented).
- [ ] `make check` still passes (lint + tests + dbt-parse + web).
