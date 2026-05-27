# ADR 008: Remove Airflow entirely to unlock SQLAlchemy 2.0 for pgvector

- Status: Accepted
- Date: 2026-05-27
- Supersedes: ADR 003 (Airflow on Railway)
- Extends: ADR 006 (AWS deploy — removed Airflow from production)

## Context

TM-32 migrated the RAG layer to a pgvector vector store managed by
`llama-index-vector-stores-postgres`. That library requires SQLAlchemy
2.0 at runtime: on 1.4 the `postgresql+psycopg` (psycopg3) dialect does
not load (`NoSuchModuleError`) and the ORM `delete(ref_doc_id=...)` path
raises `UnevaluatableError`.

`apache-airflow` 2.x pins `SQLAlchemy<2.0`. Because `uv` resolves a single
universal lock for the whole workspace, that pin forced SQLAlchemy 1.4.54
everywhere — including the production image, whose
`uv sync --frozen --no-dev --group dbt --group rag` does **not** install
Airflow but still installs the locked SQLAlchemy version. The net effect:
both RAG ingest (write) and agent retrieval (read) failed against a live
Postgres. Unit tests use fakes, so the breakage was invisible until the
first off-box ingest against the real Supabase database.

ADR 006 had already removed Airflow from production (host cron runs
`dbt build` and the weekly RAG ingest). Airflow survived only as a
local-dev dependency and the tech stack listed it as a "locked" choice,
so fully removing it warrants its own ADR.

## Decision

Remove Airflow entirely from the project:

- Drop `apache-airflow>=2.10,<3.0` from the `dev` dependency group.
- Pin `sqlalchemy>=2.0` explicitly in the `rag` group (the library's
  metadata only declares `>=1.4`, which understates its real floor).
- Delete `airflow/` (DAGs, Dockerfile, `requirements.txt`),
  the Compose `airflow-init` / `airflow-webserver` / `airflow-scheduler`
  services and the `airflow-logs` volume, `tests/airflow/`, the Makefile
  `airflow-test` target, the mypy `airflow` override, and the pytest
  `airflow` marker.

Batch orchestration is host cron in every environment, matching the
production reality established by ADR 006.

## Consequences

- SQLAlchemy resolves to 2.0.x; the pgvector dialect loads and the store
  works on both the sync (psycopg3) and async (asyncpg) paths.
- No local Airflow webserver/scheduler or DagBag-parse test. The two
  former DAGs (`dbt_nightly`, `rag_ingest_weekly`) are cron entries on the
  box (`/etc/cron.d/tfl-monitor`).
- The CLAUDE.md tech-stack table is updated to list host cron instead of
  Airflow as the batch-orchestration choice.
- A live-Postgres integration test now exercises `build_vector_store`
  (dialect load, ORM delete, query path) so a future SQLAlchemy/dialect
  regression cannot slip past the fake-backed unit tests again.
