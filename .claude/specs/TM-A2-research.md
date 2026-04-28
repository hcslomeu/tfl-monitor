# TM-A2 — Research (Phase 1)

Read-only exploration that frames the Airflow DAGs WP. Captures the state
of the repo, the entrypoints we will orchestrate, the Compose service
already in place, and the operator/test choices that fit the lean rules
in `CLAUDE.md`. No implementation here — see `TM-A2-plan.md`.

## 1. Where TM-A2 sits in the codebase

- **PROGRESS.md row:** Phase 5, track `A-infra`, blocked by `TM-C3`
  (already ✅ 2026-04-28). Sibling parallel slot per `SETUP.md` §10.1 is
  TM-D4 (already ✅).
- **Linear issue:** `TM-16`. PR will close it.
- **Branch:** worktree `agent-a7fd3fe78212bb612` is parked on `main`.
  Implementation branch will be `feature/TM-A2-airflow-dags`.
- **Open PRs on `origin`:** `#38` (TM-D2) and `#39` (TM-E1b). Neither
  touches `airflow/`, `pyproject.toml`, or `Makefile` in conflicting
  ways, so this WP can proceed independently.
- **Lean discipline (CLAUDE.md Principle #1):**
  - rule 1 (one `pyproject.toml` at root) — extra deps go into the same
    file, not a sub-package.
  - rule 4 (no factory without two consumers) — DAGs call existing
    entrypoints via `BashOperator`, no operator subclassing.
  - rule 5 (no nested `BaseSettings`) — Airflow reads its own env vars
    from Compose; no second config layer.
  - rule 6 (no custom logging wrapper) — Airflow + task stdout into
    Logfire is enough; no observability scaffolding here.
  - rule 8 (one tool per job) — no celery/k8s executor scaffolding,
    LocalExecutor stays.

## 2. What already exists in `airflow/`

`airflow/` was scaffolded by TM-A1:

```
airflow/
├── Dockerfile         # FROM apache/airflow:2.10.3 ; pip install -r requirements.txt
├── README.md          # "Scaffold only — DAGs land in TM-A2."
├── dags/.gitkeep      # empty placeholder
└── requirements.txt   # "# Additional Airflow provider packages land in TM-A2."
```

`docker-compose.yml` exposes three Airflow services on the default
profile (no profile gating):

| Service | Role | Notes |
|---|---|---|
| `airflow-init` | one-shot DB migrate + admin user | `_AIRFLOW_DB_MIGRATE=true`, `_AIRFLOW_WWW_USER_CREATE=true`, `command: version` |
| `airflow-webserver` | UI on `localhost:8082` | depends on `airflow-init` completion, healthcheck on `/health` |
| `airflow-scheduler` | scheduler loop | LocalExecutor, healthcheck via `airflow jobs check` |

Volume mounts (all three):

- `./airflow/dags:/opt/airflow/dags` — host-mounted DAG folder, so any
  new file under `airflow/dags/` is picked up live by the scheduler.
- `airflow-logs:/opt/airflow/logs` — named volume.

Environment already wired:

- `AIRFLOW__CORE__EXECUTOR=LocalExecutor`
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://…@postgres/…`
  (shared with the warehouse; ADR 003 confirms the same Postgres in
  prod on Supabase).
- `AIRFLOW__CORE__LOAD_EXAMPLES=False`

`AIRFLOW__CORE__DAGS_FOLDER` is **not** set explicitly — Airflow
defaults to `/opt/airflow/dags`, which matches the bind mount. Nothing
to change.

## 3. Entrypoints to orchestrate

### 3.1 dbt project

- `dbt/dbt_project.yml` profile `tfl_monitor`, models under
  `dbt/models/{staging,intermediate,marts}/`, target `dev` writes to
  schema `analytics` reading the same Postgres as the warehouse.
- `dbt/profiles.yml` reads `POSTGRES_*` from env. Two outputs: `dev`
  and `ci`. Inside the Airflow container we need `dev` (LocalExecutor
  shares the Compose Postgres).
- Existing `[tool.taskipy.tasks]` only has `dbt-parse`. There is **no**
  `dbt run` / `dbt test` / `dbt build` task. We will add minimal
  taskipy entries (`dbt-run`, `dbt-test`) to keep the DAG one-line.
- `dbt build` (= `run` + `test` + `seed` + `snapshot` per dbt docs)
  runs everything in dependency order; the Linear acceptance criterion
  asks for `dbt build`, so we use that.

### 3.2 RAG ingestion

- `src/rag/ingest.py` exposes `python -m rag.ingest` with three flags:
  `--refresh-urls`, `--force-refetch`, `--dry-run`.
- The script is idempotent: HTTP 304 short-circuits, stable chunk IDs,
  failure of any single doc surfaces as `SystemExit(1)`.
- Required env: `OPENAI_API_KEY`, `PINECONE_API_KEY`,
  `PINECONE_INDEX`, `EMBEDDING_MODEL`. All already enumerated in
  `.env.example`. Airflow inherits these from the Compose `.env` if
  passed through the service environment.

### 3.3 Static TfL ingest (Linear acceptance criterion)

The Linear issue lists a second DAG `static_ingest` that "loads static
TfL data" (e.g. `ref.lines`, `ref.stations`). **No such pipeline
exists in the repo today** — TM-B4 only covers live producers/
consumers. TM-C3 even notes that `mart_bus_metrics_daily` "returns 0
rows until TM-A2 populates `ref.lines`". The orchestrator brief
explicitly substitutes `rag_ingest_weekly` for `static_ingest` and
defers the static-ingest DAG. Open question Q1 below.

### 3.4 Streaming producers/consumers

- `src/ingestion/producers/{line_status,arrivals,disruptions}.py` are
  long-running daemons (`run_forever`).
- `src/ingestion/consumers/{...}.py` mirror them.
- These are **already managed by Compose** (profile `ingest`, services
  `tfl-line-status-producer` etc.). They are not a fit for a batch DAG
  and the brief explicitly excludes them.

## 4. Operator + execution model decision

Two viable options inside the Airflow container:

| Option | Pros | Cons |
|---|---|---|
| **A. `BashOperator` + `uv run`** | Single source of truth — DAG calls the same `uv run task <name>` the developer runs locally. No venv wiring. Trivial to read. | Requires `uv` to be on PATH inside the Airflow image. |
| **B. `PythonOperator`** importing `rag.ingest:run_ingestion` | No subprocess overhead. Direct exception → task failure. | Couples Airflow venv to project deps; risk of conflict between Airflow constraints and the project's Pinecone/Docling stack. Heavier image. |

CLAUDE.md rule 4 ("no abstraction without two consumers") and rule 8
("one tool per job") plus the brief's "lean rule" point at **A**.

**Concrete plan for option A:**

- Bake `uv` into the Airflow Docker image. Two ways:
  - `pip install uv` inside `airflow/Dockerfile` — adds `uv` to the
    same Python env as Airflow. Trivial, no PATH gymnastics.
  - Copy the `astral-sh/uv` binary in via a multi-stage. Smaller, but
    extra Docker complexity for marginal gain.

  Pick the `pip install uv` route.

- Mount the project root into the Airflow container so `uv run` can
  resolve `pyproject.toml`. The current Compose mounts only
  `./airflow/dags`. We add `.:/opt/tfl-monitor:ro` and set
  `working_dir: /opt/tfl-monitor` for the scheduler/webserver/init.
  However this **modifies docker-compose.yml** which is in scope
  (per the brief: *"only `airflow/`, `docker-compose.yml`,
  `pyproject.toml` (deps if needed), `Makefile` (one extra task at
  most), and `PROGRESS.md` should change"*).

- Tasks invoked: `bash -lc 'cd /opt/tfl-monitor && uv run task dbt-build'`
  and similarly for `rag-ingest`.

**Open question Q2:** mount `:ro` (read-only) is safe but `dbt build`
writes to `dbt/target/` — the project root must be writable for that
subdir, OR we point dbt's target-path at a writable volume. Decision in
the plan: mount the project rw but at a separate path, OR use the
default mount and let `target/` be ephemeral. Simpler: add `target/` to
`.gitignore` (already there via `clean-targets`) and mount the project
read-write, since the Airflow container runs as `user: 50000:0` which
already has root group access.

## 5. Schedules

Per the brief and Linear issue:

- **`dbt_nightly`** (= the brief's `dbt_daily`): one run per day after
  the previous day's data has fully landed. UTC midnight + an hour gives
  the streaming consumers time to flush late events. Cron:
  `"0 1 * * *"`. `catchup=False`, `max_active_runs=1`.
  - We name it `dbt_nightly` (matches Linear's wording) but
    documentation aligns with the brief's "daily" cadence — they are
    the same thing.
- **`rag_ingest_weekly`**: weekly is enough — TfL strategy docs change
  on a multi-month cadence, and the script is idempotent on 304s. Cron:
  `"0 3 * * 1"` (Monday 03:00 UTC, off-peak for TfL static asset
  servers).

Both DAGs read schedule from the DAG file directly. No env-driven
schedule layer (CLAUDE.md rule 5 — no nested config).

`start_date`: `pendulum.datetime(2026, 4, 28, tz="UTC")` — the day
this WP lands. `catchup=False` makes the value largely cosmetic, but
explicit is better than implicit.

## 6. Defaults across DAGs

```python
default_args = {
    "owner": "tfl-monitor",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
}
```

Tag every DAG with `["tfl-monitor", "<track>"]` for UI grouping.

`max_active_runs=1` on both: `dbt build` mutating warehouse tables and
`rag.ingest` upserting Pinecone are not safely concurrent.

## 7. Tests

DAG-level smoke tests are the bare minimum the brief requires:

1. The DAG file imports without error (catches missing imports,
   syntax mistakes, deprecated Airflow APIs).
2. `dag_id` matches the file name's intent.
3. `default_args` are present with `retries >= 1`.
4. At least one task is registered.
5. No cycles (Airflow rejects cyclic DAGs at parse time, but explicit
   assertion documents the contract).

Two test patterns to choose from:

- **A. Native `airflow` import with the dev dep installed.** Cleanest;
  `uv add --dev apache-airflow>=2.10,<3.0` was verified above to lock.
  The dependency tree already pulls torch/transformers via Docling, so
  the marginal cost is moderate.
- **B. `pytest.importorskip("airflow")`.** No new dep; CI silently
  skips if Airflow is absent. Risk: tests become a no-op for any
  developer who hasn't installed Airflow manually. Defeats the purpose.

We pick **A**. To keep `make check` fast we still gate the airflow
tests behind `@pytest.mark.airflow` (per the brief's instructions) —
default `addopts` excludes them, explicit `-m airflow` opts in. This
mirrors the existing `@pytest.mark.integration` discipline.

## 8. Files-to-touch shortlist

- `airflow/dags/dbt_nightly.py` — new
- `airflow/dags/rag_ingest_weekly.py` — new
- `airflow/dags/__init__.py` — not needed (Airflow ignores it; folder
  is a DAG bag, not a Python package)
- `airflow/requirements.txt` — add `uv` (so `BashOperator` can
  `uv run` inside the container)
- `airflow/Dockerfile` — no change (the requirements.txt install
  already pulls uv into the image)
- `docker-compose.yml` — mount project root into the three Airflow
  services and set `working_dir`
- `pyproject.toml` — `apache-airflow>=2.10,<3.0` in dev group;
  `[tool.taskipy.tasks]` add `dbt-build`, `dbt-run`, `dbt-test`,
  `rag-ingest`; pytest `markers` add `airflow:` description
- `Makefile` — at most one extra target `airflow-test` (decide in the
  plan; may not be needed if `uv run pytest -m airflow tests/airflow`
  is short enough)
- `tests/airflow/__init__.py` + `tests/airflow/test_dags_parse.py`
- `PROGRESS.md` — flip `TM-A2` row to ✅ with notes
- `.claude/specs/TM-A2-{research,plan}.md` — these documents

Out of scope (deliberately untouched per WP scope rules):
`src/`, `dbt/models/`, `web/`, `contracts/`.

## 9. Open questions

- **Q1 — `static_ingest` DAG.** Linear lists this as an acceptance
  criterion but no upstream pipeline exists; `mart_bus_metrics_daily`
  documents the gap. The brief explicitly says we substitute
  `rag_ingest_weekly` and defer static ingest. The plan will record
  the substitution as a deliberate choice and surface it in the PR
  body so the author can decide whether to file a follow-up issue.
  Lean answer: defer until a real `static_ingest` business need
  surfaces (probably alongside `ref.lines` population in a new WP).
- **Q2 — `dbt target/` writability.** Mount the project root rw into
  the Airflow container. `dbt/target/` is already `.gitignore`d via
  `clean-targets`. No further work.
- **Q3 — `uv` availability inside the Airflow image.** Add `uv` to
  `airflow/requirements.txt` so the Dockerfile installs it during the
  image build. Verified above that `uv` resolves cleanly inside a
  Python 3.12 environment, which `apache/airflow:2.10.3` is.
- **Q4 — Secrets for RAG DAG (`OPENAI_API_KEY`, `PINECONE_API_KEY`).**
  Inject through Compose `environment:` blocks on the Airflow
  services, sourced from the host `.env`. No Airflow Connections /
  Variables — the brief forbids them ("Do NOT add Airflow connections
  or pool configs the project doesn't already need").
- **Q5 — Airflow `dag_id` vs file name.** Airflow looks up the DAG by
  the DAG object, not the file name, but operationally the file name
  must mirror the `dag_id` to keep the UI sortable. Stick to
  `dag_id == filename_without_suffix`.

## 10. Risks

- **R1 — Lock blow-up.** `uv add --dev apache-airflow` adds ~80
  transitive packages (providers + flask + werkzeug). Verified the
  lock resolves cleanly; FastAPI 0.136 + Starlette 1.0 still satisfy
  our constraints. Cost accepted.
- **R2 — Slow `pytest` collection.** Importing `airflow` is heavy.
  Mitigation: marker `airflow` excluded from `addopts`. `make check`
  stays under existing budget.
- **R3 — Image size.** Adding `uv` to the Airflow image is < 50 MB.
  Acceptable; the image already pulls a lot via the apache/airflow
  base.
- **R4 — Dbt running in the same Postgres as Airflow metadata.** ADR
  003 already accepts this. dbt writes to schema `analytics`; Airflow
  writes to its own metadata schema (default `public`). No collision.
- **R5 — Consumer daemons stop pulling between dbt runs.** The dbt
  build runs every 24h; the marts are at daily grain, so a momentary
  consumer hiccup does not cascade. No new health logic needed.

## 11. Verification gates (to be re-run during implementation)

1. `uv run task lint` (ruff + ruff format + mypy strict).
2. `uv run task test` (default, hermetic — airflow tests excluded).
3. `uv run pytest -m airflow tests/airflow -v` (explicit opt-in).
4. `uv run task dbt-parse` (still green after taskipy edits).
5. `uv run bandit -r src --severity-level high`.
6. `make check` end-to-end.

These appear in the plan as success gates per phase.
