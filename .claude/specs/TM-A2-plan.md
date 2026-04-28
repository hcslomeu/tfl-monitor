# TM-A2 — Plan (Phase 2)

Implementation plan for the Airflow DAGs WP. Builds on
`TM-A2-research.md`. Written before code; success criteria below are
the acceptance gate.

## 0. Decisions locked from research open questions

- **Q1 (static_ingest):** **Deferred.** The Linear-listed
  `static_ingest` DAG has no upstream `ref.lines`/`ref.stations`
  loader to call. We ship `rag_ingest_weekly` instead and record the
  deferral in the PR body so the author can file a follow-up.
- **Q2 (dbt target writability):** Mount project root **rw** into the
  Airflow services. `dbt/target/` is `.gitignore`d via `clean-targets`.
- **Q3 (uv inside Airflow image):** Add `uv` to
  `airflow/requirements.txt`. Image build installs it into the same
  Python env as Airflow, and `BashOperator` invokes `uv run`.
- **Q4 (RAG secrets):** Pass `OPENAI_API_KEY`, `PINECONE_API_KEY`,
  `PINECONE_INDEX`, `EMBEDDING_MODEL`, plus
  `LANGSMITH_*`/`LOGFIRE_TOKEN`/`ENVIRONMENT`/`APP_VERSION` through
  Compose `environment:` on the three Airflow services. **No** Airflow
  Connections / Variables.
- **Q5 (dag_id vs filename):** `dag_id == filename_without_suffix`.

## 1. Scope

| In scope | Out of scope |
|---|---|
| Two DAGs under `airflow/dags/` (`dbt_nightly`, `rag_ingest_weekly`) | A `static_ingest` DAG (no upstream loader) |
| `apache-airflow>=2.10,<3.0` as a dev dep | Custom Airflow plugin/executor/XCom backend |
| Mount project root into Airflow services + set `working_dir` | New observability tools (Prometheus / Grafana / statsd) |
| `airflow/requirements.txt` adds `uv` | Migration of the streaming consumers off Compose |
| `[tool.taskipy.tasks]` gains `dbt-build`, `dbt-run`, `dbt-test`, `rag-ingest` | Editing `src/`, `dbt/models/`, `web/`, `contracts/` |
| `tests/airflow/test_dags_parse.py` gated on `@pytest.mark.airflow` | Adding new pytest base tests outside the airflow marker |
| `Makefile` gains exactly one target `airflow-test` | More than one new Makefile target |
| `PROGRESS.md` row flipped to ✅ with notes | Editing other rows in `PROGRESS.md` |

## 2. Internal phases

### Phase 3.1 — Repo wiring (deps, taskipy, image)

Goal: the venv understands `airflow` and the Airflow image understands
`uv`.

Files:

- `pyproject.toml`:
  - `[dependency-groups] dev` += `"apache-airflow>=2.10,<3.0"`
    (already done via `uv add --dev` during research; commit the
    resulting `uv.lock`).
  - `[tool.taskipy.tasks]` += `dbt-build`, `dbt-run`, `dbt-test`,
    `rag-ingest`. Each is a one-liner shelling out to the existing
    CLIs (`dbt build --project-dir dbt --profiles-dir dbt --target dev`,
    `python -m rag.ingest`).
  - `[tool.pytest.ini_options]`:
    - `addopts` updated to also exclude `airflow`:
      `-m 'not integration and not airflow'`.
    - `markers` += `"airflow: requires apache-airflow installed; opt in with -m airflow"`.
  - `[tool.mypy.overrides]` += an `airflow.*` entry with
    `ignore_missing_imports = true` and
    `follow_untyped_imports = true` (Airflow stubs are partial).
- `airflow/requirements.txt` += `uv>=0.5`.

Success criteria:

- Automated:
  - `uv lock` exits 0.
  - `uv run python -c "import airflow; print(airflow.__version__)"` reports
    `2.10.x` or `2.11.x` (Airflow 2.10+ floor enforced via
    constraint).
  - `uv run task lint` is green.
  - `uv run task test` is green (no airflow tests collected yet —
    the marker exclusion guarantees that).
  - `uv run task dbt-parse` is green.
- Manual:
  - `airflow/Dockerfile` unchanged (the only delta is the
    `requirements.txt` line that the Dockerfile already installs).

### Phase 3.2 — Compose mount + Airflow env

Goal: the `airflow-init`, `airflow-webserver`, and `airflow-scheduler`
services see the project root and the secrets they need.

Files:

- `docker-compose.yml`:
  - Add `./:/opt/tfl-monitor` mount and
    `working_dir: /opt/tfl-monitor` on the three Airflow services.
  - Keep `./airflow/dags:/opt/airflow/dags` and
    `airflow-logs:/opt/airflow/logs` exactly as today.
  - Extend the `environment:` block on the three Airflow services
    with: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`,
    `POSTGRES_PASSWORD`, `POSTGRES_DB`, `OPENAI_API_KEY`,
    `PINECONE_API_KEY`, `PINECONE_INDEX`, `EMBEDDING_MODEL`,
    `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`,
    `LOGFIRE_TOKEN`, `ENVIRONMENT`, `APP_VERSION`. All are pass-through
    from the host `.env`. Pinecone / OpenAI vars use the
    `${VAR:-}` form so the Airflow container still starts when running
    only the dbt DAG.

Success criteria:

- Automated: nothing new — Compose changes don't surface in `lint` or
  `test`.
- Manual:
  - `docker compose config` parses cleanly (smoke; not a test gate).
  - `cat docker-compose.yml | grep -c '/opt/tfl-monitor'` returns `3`
    (one mount + two `working_dir`s on the three services — verified
    visually).

### Phase 3.3 — DAGs

Goal: two DAG files that parse, schedule, and call the right
entrypoints via `BashOperator`.

Files:

- `airflow/dags/dbt_nightly.py`:
  - `dag_id="dbt_nightly"`, `schedule="0 1 * * *"`,
    `start_date=pendulum.datetime(2026, 4, 28, tz="UTC")`,
    `catchup=False`, `max_active_runs=1`, `tags=["tfl-monitor", "dbt"]`.
  - Single task `dbt_build` running:
    `bash -lc 'cd /opt/tfl-monitor && uv run dbt build --project-dir dbt --profiles-dir dbt --target dev'`.
    Inline `uv run dbt build ...` rather than `uv run task dbt-build`
    so the DAG still works if a future taskipy refactor renames the
    task.
- `airflow/dags/rag_ingest_weekly.py`:
  - `dag_id="rag_ingest_weekly"`, `schedule="0 3 * * 1"`, same
    `start_date`/`catchup`/`max_active_runs`,
    `tags=["tfl-monitor", "rag"]`.
  - Single task `rag_ingest` running:
    `bash -lc 'cd /opt/tfl-monitor && uv run python -m rag.ingest'`.

Both DAGs share `default_args = {"owner": "tfl-monitor", "retries": 2,
"retry_delay": timedelta(minutes=5), "depends_on_past": False,
"email_on_failure": False, "email_on_retry": False}`.

A short module docstring explains the schedule and the entrypoint.
No DAG-level Python beyond imports + DAG/Task instantiation.

Success criteria:

- Automated:
  - `uv run pytest -m airflow tests/airflow -v` (added in 3.4) green.
  - `uv run task lint` green (ruff + mypy clean on the DAG files).
- Manual:
  - `docker compose up airflow-webserver` shows both DAGs in the UI
    without import errors. **Not a CI gate** — author smoke-tests
    locally.

### Phase 3.4 — Tests

Goal: a single test module that proves both DAGs parse and meet the
contract above.

Files:

- `tests/airflow/__init__.py` (empty marker file).
- `tests/airflow/test_dags_parse.py`:
  - Module-level `pytestmark = pytest.mark.airflow`.
  - Discover DAG files by globbing `airflow/dags/*.py`.
  - For each file: load the module via `importlib.util` and assert:
    - The module exposes at least one `airflow.models.dag.DAG`
      instance through Airflow's `DagBag`.
    - `dag.dag_id` equals the file stem.
    - `dag.default_args["retries"] >= 1`.
    - `dag.default_args["owner"] == "tfl-monitor"`.
    - `len(dag.tasks) >= 1`.
    - `dag.catchup is False`.
    - `dag.max_active_runs == 1`.
    - `dag.schedule_interval` (or `dag.schedule`) is a non-empty
      string.
  - One pytest parametrised function: `test_dag(dag_file)`.
  - Use `airflow.models.dagbag.DagBag(dag_folder=...,
    include_examples=False)`. Assert `dag_bag.import_errors == {}`.

- `pyproject.toml` (already in 3.1) registers the marker.

Success criteria:

- Automated:
  - `uv run pytest -m airflow tests/airflow -v` green, exit 0, with
    two tests collected (one per DAG file).
  - `uv run task test` still excludes the airflow tests and stays
    green.
- Manual: none.

### Phase 3.5 — Makefile + PROGRESS

Goal: a discoverable `make` target for the gated airflow tests, and
the progress row updated.

Files:

- `Makefile`:
  - Add the `airflow-test` target to `.PHONY` and a help-tagged stub:
    ```make
    airflow-test: ## Run airflow DAG-parse tests (requires apache-airflow installed)
    	uv run pytest -m airflow tests/airflow -v
    ```
  - Total Makefile target count after the edit: 9 → 10. Well under
    the ≤15 ceiling.
- `PROGRESS.md`: flip `TM-A2` row from ⬜ to `✅ 2026-04-28` with a
  one-paragraph English note covering the two DAGs, schedules,
  operator choice, and the airflow marker.

Success criteria:

- Automated: `make check` end-to-end green.
- Manual: `make help` lists `airflow-test`.

## 3. Files-to-touch summary

```
airflow/dags/dbt_nightly.py            (new)
airflow/dags/rag_ingest_weekly.py      (new)
airflow/requirements.txt               (+ uv)
docker-compose.yml                     (mount + working_dir + env on 3 svcs)
pyproject.toml                         (+ apache-airflow dev dep, taskipy tasks, pytest marker, mypy override)
uv.lock                                (regenerated by uv add)
Makefile                               (+ airflow-test target)
tests/airflow/__init__.py              (new)
tests/airflow/test_dags_parse.py       (new)
PROGRESS.md                            (flip TM-A2 row)
.claude/specs/TM-A2-research.md        (Phase 1 artifact)
.claude/specs/TM-A2-plan.md            (this file)
```

Untouched (per WP scope rules): `src/**`, `dbt/models/**`,
`dbt/profiles.yml`, `dbt/dbt_project.yml`, `web/**`, `contracts/**`,
`airflow/Dockerfile`, the existing `airflow/dags/.gitkeep` (we leave
it; harmless).

## 4. Acceptance criteria (non-functional)

- **WP scope respected:** `git diff --name-only main...HEAD` returns
  only the files in §3.
- **Lean:** the change adds 0 abstractions, 0 plugins, 0 new
  Makefile targets beyond `airflow-test`, 0 new env layers.
- **CLAUDE.md compliance:** all artifacts persisted to git are in
  English; chat replies to the author stay PT-BR; commit subject ≤72
  chars; conventional commits; no `Co-Authored-By`; no heredoc in
  the commit command.

## 5. What we're NOT doing

- **No `static_ingest` DAG.** Deferred — see `TM-A2-research.md`
  §3.3 + §9 Q1. Re-evaluate when a `ref.lines` loader is built. The
  PR body surfaces this gap.
- **No Airflow plugin / custom operator / custom XCom backend.**
  `BashOperator` covers the two tasks. CLAUDE.md rule 4.
- **No Airflow Connections / Variables.** Secrets injected via
  Compose env per Q4. Brief explicitly forbids it.
- **No CeleryExecutor / KubernetesExecutor.** ADR 003 locks
  LocalExecutor.
- **No new observability tools.** Logfire + LangSmith stay the
  stack. CLAUDE.md.
- **No edits to TM-D2 / TM-E1b** even though their PRs touch nearby
  surfaces — they merge into `main` independently.
- **No `dbt-parse` task replacement** — keep it for its current CI
  consumer.
- **No editing of `airflow/Dockerfile`.** The new line in
  `requirements.txt` flows through automatically on `docker compose
  build airflow-init`.

## 6. Test strategy

| Test file | Asserts |
|---|---|
| `tests/airflow/test_dags_parse.py::test_dag_bag_no_import_errors` | `DagBag(include_examples=False, dag_folder=airflow/dags).import_errors == {}` |
| `tests/airflow/test_dags_parse.py::test_dag[dbt_nightly]` | `dag_id`, `default_args.owner`, `default_args.retries>=1`, `default_args.retry_delay` is timedelta, `len(tasks)>=1`, `catchup=False`, `max_active_runs=1`, `schedule` non-empty |
| `tests/airflow/test_dags_parse.py::test_dag[rag_ingest_weekly]` | same set of assertions |

All gated on `pytest.mark.airflow`. Default `make check` excludes
them; explicit `make airflow-test` (or `uv run pytest -m airflow ...`)
runs them.

## 7. Verification gates per phase

| Phase | Gate |
|---|---|
| 3.1 | `uv run task lint` + `uv run task test` + `uv run task dbt-parse` green |
| 3.2 | `docker compose config` parses (smoke) |
| 3.3 | `uv run pytest -m airflow tests/airflow -v` green (after 3.4) |
| 3.4 | same as 3.3 |
| 3.5 | `make check` green; `make help` lists `airflow-test` |
| Final | `uv run bandit -r src --severity-level high` green; `make check` green; both DAGs visible in the local Airflow UI when `docker compose up airflow-webserver` runs |

## 8. Rollout / commit

Single commit on `feature/TM-A2-airflow-dags`:

```
feat(airflow): TM-A2 dbt + rag DAGs (TM-16)
```

Body chains multiple `-m` flags, summarising:
1. New DAGs and their cron schedules.
2. `BashOperator` + `uv run` rationale (lean, single-source-of-truth).
3. Deferred work: `static_ingest` DAG awaits an upstream `ref.*`
   loader.
4. Verification gates passed.

PR body explicitly references `Closes TM-16`, lists the DAGs, the
gates, and an "Out of scope" pull from §5.
