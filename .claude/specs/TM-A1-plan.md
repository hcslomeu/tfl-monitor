# TM-A1 — Implementation plan (Phase 2)

Source: TM-3 acceptance criteria + Round 3 follow-up comment on TM-3 + the
Phase 1 research at `TM-A1-research.md`.

## Summary

The Compose stack was delivered as part of the TM-000 scaffold. The real TM-A1
work is: (a) fold the Round 3 DB-default follow-up into
`contracts/sql/001_raw_tables.sql`, (b) prove the stack boots healthy, (c) add
a narrow smoke test so the DDL contract is checked automatically when Postgres
is reachable. No new services, no new Make targets.

## What we're NOT doing

- Adding a dedicated Airflow metadata Postgres (→ ADR 003 / TM-A3).
- Provisioning hosted Postgres or Redpanda (→ Phase 7).
- Writing Airflow DAGs, consumers, or producers (→ TM-A2 / TM-B*).
- Swapping Docker images, renaming services, or touching the frontend.
- Running `make up` inside CI. Docker-dependent tests are gated on
  `DATABASE_URL` and only executed on demand.

## Sub-phases

### Phase 3.1 — SQL defaults (Round 3 follow-up)

- Edit `contracts/sql/001_raw_tables.sql`:
  - Add `CREATE EXTENSION IF NOT EXISTS pgcrypto;` at the top (before the
    `CREATE SCHEMA` statement).
  - For each of `raw.line_status`, `raw.arrivals`, `raw.disruptions`:
    - `event_id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
    - `ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- Keep `event_type`, `source`, `payload` unchanged.
- Re-run `uv run task dbt-parse` to confirm dbt sources still resolve against
  the updated DDL (no column rename, only defaults — should be inert).

### Phase 3.2 — Compose boot validation

- From a clean state: `make clean && make up`.
- Wait, then `docker compose ps` — every declared service (excluding the
  `ui`-profile `redpanda-console`) must be `healthy` or, for `airflow-init`,
  `exited (0)`.
- Spot-check:
  - `docker compose exec postgres psql -U tflmonitor -d tflmonitor -c '\dn'`
    → lists `raw` and `ref`.
  - `docker compose exec postgres psql -U tflmonitor -d tflmonitor -c '\dt raw.*'`
    → three tables.
  - `docker compose exec redpanda rpk cluster info` → broker up.
  - `curl -fsS http://localhost:8082/health` → Airflow 200.
  - `curl -fsS http://localhost:9000/minio/health/live` → MinIO 200.
- If any check fails: STOP and surface the failure with logs.

### Phase 3.3 — Smoke test

- Add `tests/integration/test_sql_init.py`:
  - Uses `pytest.importorskip("psycopg")`.
  - Skips unless `DATABASE_URL` env var is set (prevents CI/dev test runs
    from failing when Docker is absent).
  - Asserts:
    - Extension `pgcrypto` is installed.
    - `raw.line_status`, `raw.arrivals`, `raw.disruptions` exist with the
      expected columns.
    - `event_id` default starts with `gen_random_uuid` (matches
      `pg_attrdef.adsrc` / `pg_get_expr`).
    - `ingested_at` default resolves to `now()`.
- No new Makefile target; author runs `DATABASE_URL=... uv run pytest tests/integration` manually.
- Conftest: reuse root `conftest.py` (pure additive).

### Phase 3.4 — Documentation + progress

- Update `PROGRESS.md`: TM-A1 status ✅ with the completion date and a one-line
  note referring back to the Round 3 follow-up.
- Update `.claude/current-wp.md` after TM-A1 wraps.
- No ARCHITECTURE.md changes unless something genuinely new landed.

### Phase 3.5 — Verification gate

Before opening the PR, run:

```bash
make check
DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \
  uv run pytest tests/integration -v
```

Expect both to exit 0.

## Success criteria (copy of research, now checkable)

- [ ] `contracts/sql/001_raw_tables.sql` contains `pgcrypto` extension and
  the two defaults on all three raw tables, NOT NULL preserved.
- [ ] `make up` reports every non-profile service `healthy` (or `exited (0)`
  for `airflow-init`).
- [ ] `tests/integration/test_sql_init.py` passes when `DATABASE_URL` is set;
  skips cleanly when unset.
- [ ] `make check` still passes.
- [ ] `PROGRESS.md` reflects the new status.
- [ ] PR opened against `main` with description in English.

## Open questions (need author confirmation)

- **Q1** Is smoke-testing via `DATABASE_URL`-gated pytest acceptable, or
  should I set up a GitHub Actions service container to run it in CI now?
  Recommendation: gate locally for now; CI service containers can come in
  TM-A3 when we touch the pipeline anyway.
- **Q2** Should `make up` wait for health (blocking) instead of printing
  `docker compose ps` and exiting? Recommendation: leave it non-blocking —
  `docker compose up --wait` adds ~90s to every dev loop and authors can
  re-run `docker compose ps` themselves.

Proceed to Phase 3 once these are answered (or silently accepted via Auto).
