# TM-000 — Implementation plan (Phase 2)

Source of truth is `.claude/specs/TM-000-spec.md`. This plan turns that spec into
executable sub-phases.

Locked inputs (author decisions carried from conversation):

- **A1** Move spec: `git mv TM-000-spec.md .claude/specs/TM-000-spec.md`.
- **A2** `SETUP.md` stays at repo root untouched.
- **A3** `README.md` overwritten with the final content (spec §11 intent —
  README already matches; confirm and keep).
- **A4** `pyproject.toml` replaced integrally by spec §9 block; run `uv sync`.
- **A5** Fixture fetcher (`scripts/fetch_tfl_samples.py`) is **author-gated**:
  stop and ask before executing.
- **A6** Next.js scaffold via `pnpm create next-app` **first**, then layer
  spec-mandated files on top.
- **A7** `current-wp.md` = single line "`TM-000 — Contracts and scaffold
  (in progress)`".
- **A8** CI passes `POSTGRES_*` env vars to `dbt-parse`; `dbt/profiles.yml`
  exposes `ci` + `dev` targets.
- **A9** (decided mid-execution) Replace unsupported `[tool.uv.scripts]` with
  `taskipy` in `[tool.taskipy.tasks]`; invoke via `uv run task <name>`.
  Makefile slimmed to system orchestration only (Docker, `check`, bootstrap,
  seed, openapi-ts); Python dev tasks live in pyproject.
- **S1** `scripts/seed_fixtures.py` = stub that raises `SystemExit(1)` and
  prints a stderr pointer to TM-A1.
- **S2** `airflow/Dockerfile` = `FROM apache/airflow:2.10.3` + `COPY` and
  `RUN pip install -r requirements.txt`. `airflow/requirements.txt` = empty
  file with a comment pointing to TM-A2.
- **S3** `web/lib/mocks/*.json` derived from `contracts/openapi.yaml` examples.
  Examples must exist for every 200 response. Mock payload basis: lines
  Victoria, Piccadilly, Elizabeth; 5 disruptions; reliability 85–98 %.
- **S4** `dbt/profiles.yml` two targets: `ci` (`postgres/postgres/postgres`),
  `dev` (env vars from `.env`).

Hard rules that override any contradictory impulse mid-execution:

- **R1** If `uv sync` fails with a resolver conflict, **STOP** and notify the
  author. Never silently downgrade a dependency floor.
- **R2** If the TfL API response contradicts §5.1, **STOP** and notify.
- **R3** If `shadcn` CLI prompts differ from "Default / Slate / CSS
  variables=Yes", **STOP** and notify.
- **R4** If any acceptance criterion in §16 looks unreachable in the time
  budget, surface it immediately (spec §19).
- **R5** Fixture sub-phase (sub-phase 13) stops at the author gate before
  calling the TfL API.

---

## Directory of sub-phases

| # | Title | Outputs |
|---|---|---|
| 1 | Housekeeping | `.gitignore`, `.DS_Store` untracked, spec moved |
| 2 | `pyproject.toml` + `uv sync` | real pyproject, `uv.lock` |
| 3 | Contracts — Pydantic schemas | `contracts/schemas/*.py` |
| 4 | Contracts — SQL DDL + dbt sources | `contracts/sql/*.sql`, `contracts/dbt_sources.yml` |
| 5 | Contracts — OpenAPI 3.1 + README | `contracts/openapi.yaml`, `contracts/README.md` |
| 6 | Tests skeleton | `tests/__init__.py`, `test_health.py`, `test_contracts.py` (skip-if-missing) |
| 7 | Service scaffolds | `src/api/*`, `src/agent/*`, `src/ingestion/*` |
| 8 | Local infra | `docker-compose.yml`, `.env.example`, `.dockerignore`, `Makefile`, `scripts/seed_fixtures.py` stub |
| 9 | dbt scaffold | `dbt/*` |
| 10 | Airflow scaffold | `airflow/*` |
| 11 | Web scaffold (generator) | `web/*` via `pnpm create next-app` + biome + shadcn |
| 12 | Web overlays + mocks | `next.config.ts`, placeholders, `lib/api-client.ts`, `lib/types.ts`, `lib/mocks/*.json` |
| 13 | **Fixtures (author-gated)** | `scripts/fetch_tfl_samples.py`, `tests/fixtures/*.json` |
| 14 | Docs + ADRs | 4 ADRs, `ARCHITECTURE.md`, `README.md` overwrite, `PROGRESS.md`, `.claude/current-wp.md`, `LICENSE` |
| 15 | CI + PR template | `.github/workflows/ci.yml`, `.github/pull_request_template.md` |
| 16 | End-to-end validation | `make check` green |
| 17 | Git handoff | Commands as text for author |

---

## Sub-phase 1 — Housekeeping

### Files touched

| Path | Action |
|---|---|
| `.gitignore` | overwrite with SETUP.md §2.2 block (already covers `.DS_Store`) |
| `.DS_Store` | `git rm --cached .DS_Store` (remove from index, leave on disk) |
| `TM-000-spec.md` | `git mv TM-000-spec.md .claude/specs/TM-000-spec.md` |

`.gitignore` body (verbatim SETUP.md §2.2, already includes `.DS_Store` so no
additional pattern needed):

```
.env
.env.local
__pycache__/
*.pyc
.venv/
node_modules/
.DS_Store
.ruff_cache/
.mypy_cache/
.pytest_cache/
dist/
build/
*.egg-info/
```

### Success — automated

- `git check-ignore .DS_Store` returns 0.
- `git ls-files | grep -v TM-000-spec.md | grep TM-000` shows only
  `.claude/specs/TM-000-spec.md`.
- Root-level `TM-000-spec.md` gone from working tree.

### Success — manual

- Working tree clean after staging; diff shows rename for spec, deletion for
  `.DS_Store` in the index, `.gitignore` populated.

### Risk mitigations

- **Risk 8 (DS_Store)** handled here (`git rm --cached`).
- **Risk 9 (move vs copy)** handled here (`git mv` yields a rename diff).

---

## Sub-phase 2 — `pyproject.toml` + `uv sync`

### Files touched

| Path | Action |
|---|---|
| `pyproject.toml` | overwrite integrally with spec §9 block |
| `uv.lock` | generated by `uv sync` |

### Commands

```bash
uv sync
```

### Success — automated

- `uv.lock` exists and is non-empty.
- `uv run python -c "import fastapi, pydantic, langgraph, logfire, langsmith, llama_index, pinecone, docling, anthropic, openai, httpx, psycopg, aiokafka, pydantic_ai"` exits 0.

### Success — manual

- No resolver warnings about incompatible constraints in `uv sync` output.

### Risk mitigations

- **Risk 3 (uv sync resolver conflict)**: on first failure, stop and hand the
  error to the author (per R1). Do **not** float versions down without
  approval.
- **Risk 5 (psycopg binary + logfire[psycopg] on macOS arm64)**: if the bundle
  fails to resolve, stop and escalate (R1). Do not swap to `psycopg[binary]`
  without the logfire extra silently.

---

## Sub-phase 3 — Pydantic schemas

### Files touched

| Path | Content summary |
|---|---|
| `contracts/schemas/__init__.py` | re-exports `LineStatusEvent`, `ArrivalEvent`, `DisruptionEvent`, `Event` and common enums |
| `contracts/schemas/common.py` | `TransportMode` enum, `StatusSeverity` IntEnum (0–20), `DisruptionCategory` enum, type aliases, generic `Event[P]` envelope (spec §5.1) |
| `contracts/schemas/line_status.py` | `LineStatusPayload`, `LineStatusEvent = Event[LineStatusPayload]` with `TOPIC_NAME = "line-status"` |
| `contracts/schemas/arrivals.py` | `ArrivalPayload`, `ArrivalEvent = Event[ArrivalPayload]` with `TOPIC_NAME = "arrivals"` |
| `contracts/schemas/disruptions.py` | `DisruptionPayload`, `DisruptionEvent = Event[DisruptionPayload]` with `TOPIC_NAME = "disruptions"` |

Fields per spec §5.1 verbatim:

- `LineStatusPayload`: `line_id`, `line_name`, `mode`, `status_severity` (int
  0–20), `status_severity_description`, `reason` (opt), `valid_from`,
  `valid_to`. Model-level validator: `valid_to > valid_from` (spec-endorsed).
- `ArrivalPayload`: `arrival_id`, `station_id`, `station_name`, `line_id`,
  `platform_name`, `direction`, `destination`, `expected_arrival`,
  `time_to_station_seconds`, `vehicle_id` (opt).
- `DisruptionPayload`: `disruption_id`, `category`, `category_description`,
  `description`, `summary`, `affected_routes: list[str]`,
  `affected_stops: list[str]`, `closure_text`, `severity`, `created`,
  `last_update`.

All models `frozen=True`. Timestamps `datetime` UTC. `TOPIC_NAME` declared as
`ClassVar[str]`.

### Success — automated

- `uv run python -c "from contracts.schemas import LineStatusEvent, ArrivalEvent, DisruptionEvent"` exits 0 (spec §16 AC).
- `uv run mypy src contracts` passes (strict mode).
- `uv run ruff check contracts` green.

### Success — manual

- Docstrings present, minimal, English (CLAUDE.md §Docstring format).
- No custom serialisers or factory methods beyond the one `valid_to >
  valid_from` validator.

### Risk mitigations

- **Risk 1 (TfL schema drift)**: verified at sub-phase 13 against real
  fixtures; if fails, STOP (R2).

Note on import path: `pyproject.toml` sets `pythonpath = ["src"]` for pytest
but `contracts/` is imported directly (top-level package). The hatch wheel
config already lists only `src/ingestion`, `src/api`, `src/agent`; we extend it
to include `contracts` so `uv sync` picks the package up. That is a one-line
addition inside the `[tool.hatch.build.targets.wheel]` block.

---

## Sub-phase 4 — SQL DDL + dbt sources

### Files touched

| Path | Content |
|---|---|
| `contracts/sql/001_raw_tables.sql` | `raw` schema; 3 append-only tables (line_status, arrivals, disruptions) with `event_id PK, ingested_at, event_type, source, payload JSONB` |
| `contracts/sql/002_reference_tables.sql` | `ref` schema; `ref.lines`, `ref.stations` per §5.3 |
| `contracts/sql/003_indexes.sql` | `BTREE` on `ingested_at DESC` + `GIN` on `payload` for each raw table |
| `contracts/dbt_sources.yml` | one `source` named `tfl` with tables `line_status`, `arrivals`, `disruptions` (raw) and `lines`, `stations` (ref); tests `not_null` on `event_id`, `ingested_at`; `unique` on `event_id` for raw tables |

All DDL files use `CREATE ... IF NOT EXISTS` (idempotent, spec requirement).

### Success — automated

- `docker compose up -d postgres` → `psql ... -f 001 -f 002 -f 003` returns 0
  against an empty Postgres 16 (§16 AC).
- `sqlfluff` not required (not in stack); we trust Postgres parser.

### Success — manual

- Re-running the three scripts on the same DB produces no errors (idempotency).
- Columns match the Pydantic payloads (no drift).

### Risk mitigations

- **Risk 4 (dbt parse needs live DB)**: addressed in sub-phase 9 via
  `profiles.yml` pointing at reachable defaults; `dbt parse` itself does not
  connect unless `--target` forces a connection. Document in sub-phase 9.

---

## Sub-phase 5 — OpenAPI 3.1 + `contracts/README.md`

### Files touched

| Path | Content |
|---|---|
| `contracts/README.md` | one sentence: "Changes here require an ADR and a broadcast." plus brief index of sub-files |
| `contracts/openapi.yaml` | OpenAPI 3.1, 8 endpoints, every 200 response with `example`, RFC 7807 error schema, CORS note |

Endpoints (spec §5.2):

| Method | Path | operationId | Response schema |
|---|---|---|---|
| GET | `/health` | `get_health` | `HealthStatus` |
| GET | `/api/v1/status/live` | `get_status_live` | `list[LineStatus]` |
| GET | `/api/v1/status/history` | `get_status_history` | `list[LineStatus]` |
| GET | `/api/v1/reliability/{line_id}` | `get_line_reliability` | `LineReliability` |
| GET | `/api/v1/disruptions/recent` | `get_recent_disruptions` | `list[Disruption]` |
| GET | `/api/v1/bus/{stop_id}/punctuality` | `get_bus_punctuality` | `BusPunctuality` |
| POST | `/api/v1/chat/stream` | `post_chat_stream` | SSE `text/event-stream` |
| GET | `/api/v1/chat/{thread_id}/history` | `get_chat_history` | `list[ChatMessage]` |

Every non-SSE 200 response carries an `example:` field keyed with realistic
data — these examples are the source for `web/lib/mocks/*.json` in
sub-phase 12.

### Success — automated

- `uv run openapi-spec-validator contracts/openapi.yaml` exits 0 (§16 AC).
- `grep "example:" contracts/openapi.yaml | wc -l` ≥ 7 (every non-SSE 200
  response has an example).

### Success — manual

- `operationId`s match the Python function names we will later wire in
  `src/api/main.py`.
- Error responses follow RFC 7807 (`application/problem+json`, `type`,
  `title`, `detail`, `status` fields).
- CORS allowlist behaviour described in the `info.description`.

### Risk mitigations

- **Risk 6 (missing `openapi-typescript` dev dep)**: declared in
  `web/package.json` in sub-phase 12.

---

## Sub-phase 6 — Tests skeleton

### Files touched

| Path | Content |
|---|---|
| `tests/__init__.py` | empty |
| `tests/test_health.py` | uses FastAPI `TestClient` on `api.main:app`; asserts `/health` returns 200 with `{"status": "ok", "dependencies": {}}` |
| `tests/test_contracts.py` | loads each fixture JSON and parses via the corresponding Pydantic event; `pytest.mark.skipif` if fixture missing, so sub-phase 6 is green even before sub-phase 13 |

### Success — automated

- `uv run task test` green immediately after sub-phase 6 (test_contracts skips;
  test_health passes).
- `uv run task test` green again after sub-phase 13 (skip turns off; real
  validation runs).

### Success — manual

- Skip message is explicit: "fixtures not yet fetched — run
  `uv run python scripts/fetch_tfl_samples.py`".

### Risk mitigations

- **Risk 1 (TfL schema drift)** exposed here once fixtures arrive; stops
  execution via R2 before silent adaptation.

---

## Sub-phase 7 — Service scaffolds

### Files touched

| Path | Content |
|---|---|
| `src/ingestion/__init__.py` | empty |
| `src/ingestion/tfl_client/__init__.py` | empty (populated in TM-B1) |
| `src/ingestion/producers/__init__.py` | empty |
| `src/ingestion/consumers/__init__.py` | empty |
| `src/api/__init__.py` | empty |
| `src/api/main.py` | spec §7.1 verbatim; 8 endpoint stubs return 501 |
| `src/api/observability.py` | spec §7.2 verbatim |
| `src/agent/__init__.py` | empty |
| `src/agent/graph.py` | spec §7.4 verbatim (no-op LangGraph, imported `validate_langsmith_env` call at module level) |
| `src/agent/observability.py` | spec §7.3 verbatim |

### Success — automated

- `uv run python -c "from api.main import app"` exits 0.
- `uv run python -c "from agent.graph import app as agent_app"` exits 0.
- `uv run python -c "from api.observability import configure_observability; from agent.observability import validate_langsmith_env"` exits 0.
- `uv run mypy src` passes.
- `uv run task test` (`tests/test_health.py`) green.

### Success — manual

- No Pydantic AI import anywhere (spec §17).
- No custom structured logging wrapper (CLAUDE.md rule 6).
- `configure_observability(app)` called once in `src/api/main.py`.

### Risk mitigations

- None specific — skeleton follows spec verbatim.

---

## Sub-phase 8 — Local infra

### Files touched

| Path | Content |
|---|---|
| `docker-compose.yml` | 6 services: `postgres`, `redpanda`, `redpanda-console`, `airflow-init` + `airflow-webserver` + `airflow-scheduler`, `minio`. Healthchecks, `restart: unless-stopped`, 90 s `start_period` tolerance, `postgres` mounts `contracts/sql/` at `/docker-entrypoint-initdb.d/` |
| `.env.example` | spec §11 verbatim |
| `.dockerignore` | `.venv`, `__pycache__`, `node_modules`, `.git`, `.mypy_cache`, etc. |
| `Makefile` | spec §10 verbatim, 7 targets: `help bootstrap up down clean check seed openapi-ts` |
| `scripts/seed_fixtures.py` | stub: docstring "Fixture seeding lands in TM-A1"; prints pointer to stderr; `raise SystemExit(1)` |

`scripts/seed_fixtures.py` stub body (final):

```python
"""Placeholder for warehouse fixture seeding.

Real implementation arrives in TM-A1 when docker-compose Postgres is
populated with sample rows for local UI development. Until then, invoking
this script fails fast so the Makefile target does not silently succeed.
"""

import sys


def main() -> None:
    sys.stderr.write(
        "seed_fixtures is not implemented yet. See work package TM-A1.\n"
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
```

### Success — automated

- `docker compose config` exits 0 (compose file parses).
- `make help` prints the 7 targets.
- `uv run python scripts/seed_fixtures.py` exits with code 1 and writes the
  "Implemented in TM-A1" message to stderr.

### Success — manual

- `make up` brings all 6 services healthy inside 90 s on the author's Mac.
- `make clean` removes volumes cleanly.
- `.env.example` contains **no** real secrets, only placeholders.

### Risk mitigations

- **Risk 7 (Airflow healthcheck > 90 s)**: `airflow-init` one-shot service
  writes metadata; `airflow-webserver` / `airflow-scheduler` `depends_on:
  airflow-init: condition: service_completed_successfully`; `start_period: 90s`
  so docker reports transient failures without marking unhealthy during
  warm-up.

---

## Sub-phase 9 — dbt scaffold

### Files touched

| Path | Content |
|---|---|
| `dbt/README.md` | one paragraph: models land in TM-C2 and later |
| `dbt/dbt_project.yml` | name `tfl_monitor`, profile `tfl_monitor`, `model-paths: ["models"]`, `source-paths: ["sources"]` |
| `dbt/profiles.yml` | profile `tfl_monitor` with `ci` and `dev` targets |
| `dbt/models/staging/.gitkeep` | empty |
| `dbt/models/intermediate/.gitkeep` | empty |
| `dbt/models/marts/.gitkeep` | empty |
| `dbt/sources/tfl.yml` | copy of `contracts/dbt_sources.yml` |

`dbt/profiles.yml`:

```yaml
tfl_monitor:
  target: dev
  outputs:
    dev:
      type: postgres
      host: "{{ env_var('POSTGRES_HOST', 'localhost') }}"
      port: "{{ env_var('POSTGRES_PORT', '5432') | int }}"
      user: "{{ env_var('POSTGRES_USER', 'tflmonitor') }}"
      password: "{{ env_var('POSTGRES_PASSWORD', 'change_me') }}"
      dbname: "{{ env_var('POSTGRES_DB', 'tflmonitor') }}"
      schema: analytics
      threads: 4
    ci:
      type: postgres
      host: "{{ env_var('POSTGRES_HOST', 'localhost') }}"
      port: "{{ env_var('POSTGRES_PORT', '5432') | int }}"
      user: "{{ env_var('POSTGRES_USER', 'postgres') }}"
      password: "{{ env_var('POSTGRES_PASSWORD', 'postgres') }}"
      dbname: "{{ env_var('POSTGRES_DB', 'postgres') }}"
      schema: analytics
      threads: 2
```

`[tool.taskipy.tasks]` entry (per A9, with `--target ci` from A8):

```
dbt-parse = "dbt parse --project-dir dbt --profiles-dir dbt --target ci"
```

### Success — automated

- `uv run task dbt-parse` exits 0 against a running Postgres container (same
  image as CI) — `dbt parse` does not execute SQL so an empty DB is enough.
- `uv run python -c "import yaml; yaml.safe_load(open('dbt/sources/tfl.yml'))"` exits 0.

### Success — manual

- `dbt/sources/tfl.yml` is a copy (not a symlink) so portability to
  Windows/CI is preserved.
- `profiles.yml` **never** reads secrets that do not have safe defaults.

### Risk mitigations

- **Risk 4 (dbt parse + live DB)**: targets default to real Postgres creds;
  CI spins up a Postgres service; local dev hits compose-managed Postgres.

---

## Sub-phase 10 — Airflow scaffold

### Files touched

| Path | Content |
|---|---|
| `airflow/README.md` | one paragraph: DAGs land in TM-A2 |
| `airflow/Dockerfile` | `FROM apache/airflow:2.10.3` + `COPY requirements.txt /requirements.txt` + `RUN pip install --no-cache-dir -r /requirements.txt` |
| `airflow/requirements.txt` | single comment line: `# Additional Airflow provider packages land in TM-A2.` |
| `airflow/dags/.gitkeep` | empty |

### Success — automated

- `docker build --dry-run -f airflow/Dockerfile airflow/` exits 0 (if the
  CLI is available; otherwise the image is validated at `make up` time).

### Success — manual

- Dockerfile is short (≤ 4 non-blank lines).

### Risk mitigations

- None specific.

---

## Sub-phase 11 — Web scaffold (generator step)

### Files touched (mostly generated)

Ordered commands (A6: generator first, then overlay):

```bash
pnpm create next-app@latest web \
    --ts --app --tailwind --import-alias "@/*" \
    --no-eslint --use-pnpm --yes
cd web
pnpm add -D @biomejs/biome openapi-typescript
pnpm biome init
pnpm dlx shadcn@latest init       # interactive: Default / Slate / CSS variables=Yes
pnpm dlx shadcn@latest add button card tabs badge skeleton alert
```

After these commands the `web/` directory exists with Next.js 15, Tailwind,
Biome config, and six shadcn primitives installed.

### Success — automated

- `pnpm --dir web install` exits 0.
- `pnpm --dir web build` exits 0.
- `pnpm --dir web exec biome check .` exits 0 (or reports only issues we
  fix in sub-phase 12).

### Success — manual

- `web/package.json` includes: `next`, `react`, `react-dom`, `typescript`,
  `@types/node`, `@types/react`, `@biomejs/biome`, `openapi-typescript`,
  `tailwindcss`, and the six shadcn component sources under
  `web/components/ui/`.
- No `eslint*` packages present (we dropped ESLint — CLAUDE.md rule 8).
- `shadcn` prompts answered Default / Slate / CSS variables = Yes.

### Risk mitigations

- **Risk 2 (shadcn CLI drift)**: if prompts differ from the expected trio,
  STOP (R3) and ask the author which answer to give. Do not guess.
- **Risk 10 (generator collisions)**: no spec-mandated files are created
  before this sub-phase; overlay happens in sub-phase 12 so the generator
  cannot clobber our files.

---

## Sub-phase 12 — Web overlays + mocks

### Files touched

| Path | Action |
|---|---|
| `web/next.config.ts` | overwrite with security headers from spec §12 |
| `web/app/page.tsx` | replace with Card "Network Now — Coming in TM-E1" |
| `web/app/reliability/page.tsx` | new — Card placeholder |
| `web/app/disruptions/page.tsx` | new — Card placeholder |
| `web/app/ask/page.tsx` | new — Card placeholder |
| `web/components/ui/.gitkeep` | empty (kept alongside generated primitives) |
| `web/lib/api-client.ts` | ~30-line typed fetch wrapper; reads `NEXT_PUBLIC_API_URL` with default `http://localhost:8000` |
| `web/lib/types.ts` | generated via `pnpm --dir web exec openapi-typescript ../contracts/openapi.yaml -o lib/types.ts` |
| `web/lib/mocks/status-live.json` | from `contracts/openapi.yaml` example for `GET /api/v1/status/live` |
| `web/lib/mocks/reliability.json` | from `contracts/openapi.yaml` example for `GET /api/v1/reliability/{line_id}` |
| `web/lib/mocks/disruptions-recent.json` | from `contracts/openapi.yaml` example for `GET /api/v1/disruptions/recent` |
| `web/public/.gitkeep` | empty |
| `web/README.md` | overwrite with one paragraph pointing at TM-E1 for real design |

Mock-data basis (S3):

- Lines: `victoria`, `piccadilly`, `elizabeth`, each with `line_name`, `mode`,
  realistic `status_severity` (e.g. 10 Good Service, 6 Severe Delays).
- 5 disruptions: two current (severity 6) on Piccadilly/Elizabeth, three
  minor (severity 9) on Victoria/Piccadilly.
- `reliability.json` for line `victoria`: `reliability_percent: 94.2`,
  `window_days: 7`, with a small histogram; Piccadilly and Elizabeth also
  included with 87.5 % and 96.1 %.
- All timestamps ISO 8601 UTC within the last 48 h (relative to
  current-date context: 2026-04-22).

### Success — automated

- `pnpm --dir web build` exits 0 on the overlaid project.
- `pnpm --dir web exec biome check .` exits 0.
- `jq empty web/lib/mocks/*.json` exits 0 for every mock (valid JSON).
- `uv run python -c "import yaml, json; spec=yaml.safe_load(open('contracts/openapi.yaml')); [json.loads(open(m).read()) for m in ['web/lib/mocks/status-live.json', 'web/lib/mocks/reliability.json', 'web/lib/mocks/disruptions-recent.json']]"` exits 0.
- `make openapi-ts` regenerates `web/lib/types.ts` idempotently.

### Success — manual

- Each mock matches the OpenAPI schema it claims to mirror (manual diff).
- No "TODO" string, no epoch-0 timestamp.

### Risk mitigations

- **Risk 6 (missing openapi-typescript)**: added to `web/package.json` devDeps
  in sub-phase 11.
- **Risk 10 (generator collisions)**: overlay happens strictly after the
  generator; we review the diff before committing.

---

## Sub-phase 13 — Fixtures (author-gated)

### Files touched

| Path | Action |
|---|---|
| `scripts/fetch_tfl_samples.py` | new — ~40-line script per spec §6.2 |
| `tests/fixtures/line_status_sample.json` | written by the script against real TfL API |
| `tests/fixtures/arrivals_sample.json` | idem |
| `tests/fixtures/disruptions_sample.json` | idem |

### Gate

**STOP** here after writing `scripts/fetch_tfl_samples.py` and before running
it. Message to the author (verbatim):

> Sub-fase 13 pronta para executar. Confirma que `TFL_APP_KEY` está presente
> em `.env` local? Aguardando "run fixtures" para prosseguir.

Only after author replies do we execute:

```bash
uv run python scripts/fetch_tfl_samples.py
```

### Success — automated

- Each JSON file > 1 kB.
- Each JSON parses (`jq empty`).
- After the fetch, `uv run task test` validates the fixtures against the Pydantic
  schemas (skip markers unload).

### Success — manual

- Author confirms `TFL_APP_KEY` configured before run.
- No API key ever present in committed files or logs.

### Risk mitigations

- **Risk 1 (TfL schema drift)**: if `test_contracts.py` fails post-fetch,
  STOP (R2). Do not adapt schemas to match payload without author review.
- **Risk 11 (running without key)**: gated explicitly.

---

## Sub-phase 14 — Docs + ADRs

### Files touched

| Path | Content |
|---|---|
| `.claude/adrs/001-redpanda-over-kafka.md` | ~1 page: API-compatible, single binary, same code local/cloud |
| `.claude/adrs/002-contracts-first.md` | why `contracts/` exists, change process, ADR requirement |
| `.claude/adrs/003-airflow-on-railway.md` | ~£5/month, portfolio signal, single scheduler source |
| `.claude/adrs/004-logfire-langsmith-split.md` | observability split, free tiers, no self-hosted stack |
| `ARCHITECTURE.md` | diagram + narrative; components table mirrors README |
| `README.md` | re-write to match spec §11 intent (current file already matches; confirm and keep; diff should be empty or trivial) |
| `PROGRESS.md` | table of WPs; TM-000 status `⬜ in progress` → flipped to `✅` at sub-phase 16 |
| `.claude/current-wp.md` | single line "`TM-000 — Contracts and scaffold (in progress)`" |
| `LICENSE` | MIT, year 2026, holder "Humberto Slomeu" |

### Success — automated

- `markdownlint` not in stack; skip.
- `test -f ARCHITECTURE.md && test -f LICENSE && test -f PROGRESS.md`.
- `grep -c "^##" .claude/adrs/*.md` ≥ 3 per file (Context/Decision/Consequences).

### Success — manual

- ADRs ≤ 1 page each.
- ARCHITECTURE.md diagram renders in GitHub preview.
- README.md intact or improved; no content drift vs current.

### Risk mitigations

- None specific.

---

## Sub-phase 15 — CI + PR template

### Files touched

| Path | Content |
|---|---|
| `.github/workflows/ci.yml` | spec §13 verbatim plus `POSTGRES_HOST/PORT/USER/PASSWORD/DB` env block for the dbt-parse step |
| `.github/pull_request_template.md` | spec §15 verbatim |

CI env block for the dbt-parse step:

```yaml
      - run: uv run task dbt-parse
        env:
          POSTGRES_HOST: localhost
          POSTGRES_PORT: "5432"
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: postgres
```

### Success — automated

- `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` exits 0.
- Local dry-run of the steps succeeds on author's laptop (where possible).

### Success — manual

- Workflow passes when the PR is opened (author observes green CI).

### Risk mitigations

- None specific at plan time; observed after PR.

---

## Sub-phase 16 — End-to-end validation

### Commands

```bash
make check
```

which runs:

- `uv run task lint` → ruff check + ruff format --check + mypy src
- `uv run task test` → pytest (now including the unskipped contract tests)
- `pnpm --dir web lint`
- `pnpm --dir web build`

Then manually:

```bash
make bootstrap          # idempotent
docker compose config   # just a sanity read
uv run openapi-spec-validator contracts/openapi.yaml
```

Flip `PROGRESS.md` TM-000 row to ✅ with today's date (2026-04-22) after all
checks pass.

### Success — automated

- All four `make check` stages green.
- `openapi-spec-validator` green.

### Success — manual

- `make up` healthy inside 90 s (optional — full compose run may be deferred
  by author).
- No secret leaked to stdout during any step.

### Risk mitigations

- If any stage fails, STOP, fix the single failure, rerun the same stage,
  then resume. No silent edits across stages.

---

## Sub-phase 17 — Git handoff

Produce (as text, not executed) the following for the author:

```bash
git checkout -b feature/TM-000-contracts-and-scaffold
git add -A
git status                                   # visual check before commit
git commit -m "feat(scaffold): bootstrap tfl-monitor contracts, infra, and service skeletons (TM-000)"
git push -u origin feature/TM-000-contracts-and-scaffold
gh pr create --title "feat: TM-000 contracts and scaffold" --body-file .github/pull_body_tm000.md
```

Single commit for the whole WP is fine — spec and CLAUDE.md rules both allow
it, and the PR template carries the full breakdown.

If the author prefers a multi-commit history, that is a post-plan
adjustment; this plan defaults to one commit.

### Success — automated

- All `git` commands shown use inline `-m "..."` only. Zero heredoc.
- No `Co-Authored-By` line.

### Success — manual

- Author copies, reviews, runs.

### Risk mitigations

- None.

---

## Acceptance-criteria traceability (spec §16)

| # | Criterion | Owning sub-phase |
|---|---|---|
| 1 | Fresh clone + `make bootstrap` + `make up` works | 8, 10, 16 |
| 2 | `uv run task test` passes | 6, 13, 16 |
| 3 | `uv run task lint` passes clean | cross-cutting (2, 3, 7), final 16 |
| 4 | `pnpm --dir web build` passes clean | 11, 12, 16 |
| 5 | All §4 files exist | 1, 3, 4, 5, 7, 8, 9, 10, 12, 14, 15 |
| 6 | `from contracts.schemas import LineStatusEvent, ArrivalEvent, DisruptionEvent` works | 3 |
| 7 | `openapi-spec-validator contracts/openapi.yaml` passes | 5 |
| 8 | DDL runs clean against empty Postgres 16 | 4, 8 |
| 9 | Real TfL fixtures committed in `tests/fixtures/` | 13 |
| 10 | API mocks in `web/lib/mocks/` | 12 |
| 11 | 4 ADRs written | 14 |
| 12 | `ARCHITECTURE.md` written | 14 |
| 13 | `README.md` written | 14 (confirm existing) |
| 14 | CI green on the PR | 15, 17 |
| 15 | `contracts/README.md` explicit on ADR rule | 5 |
| 16 | `PROGRESS.md` created with TM-000 ✅ | 14 initial, 16 flip |
| 17 | `observability.py` files exist and are imported | 7 |

---

## Risk mitigation index (from research §5)

| Risk | Title | Mitigation sub-phase |
|---|---|---|
| 1 | TfL schema drift | 13 (hard stop under R2) |
| 2 | shadcn CLI drift | 11 (hard stop under R3) |
| 3 | `uv sync` resolver conflict | 2 (hard stop under R1) |
| 4 | `dbt parse` needs live DB | 9 (profiles with live creds defaults) |
| 5 | `psycopg` / `logfire[psycopg]` packaging | 2 (hard stop under R1) |
| 6 | Missing `openapi-typescript` dev dep | 11 (explicit add) |
| 7 | Airflow healthcheck > 90 s | 8 (`airflow-init` one-shot + `start_period: 90s`) |
| 8 | `.DS_Store` tracked | 1 (`git rm --cached`) |
| 9 | spec move diff | 1 (`git mv`) |
| 10 | Generator collisions | 11 → 12 (generator first, overlay after) |
| 11 | Fixtures without key | 13 (author gate before run) |

---

## What we are NOT doing (copied from spec §17)

1. Do not implement TfL client methods beyond the fixture script.
2. Do not write dbt models (scaffold only).
3. Do not write Airflow DAGs (empty `dags/` directory).
4. Do not implement the LangGraph agent beyond the no-op.
5. Do not implement FastAPI endpoints (all return 501).
6. Do not install RAG deps beyond what's in `pyproject.toml` — do not use them.
7. Do not deploy.
8. Do not create authentication.
9. Do not build real frontend views (placeholder Cards "Coming in TM-EX").
10. Do not create a `generate_ts_types.sh` — use `make openapi-ts` directly.
11. Do not write end-to-end integration tests.
12. Do not add Prometheus/Grafana/OTel collector stacks — Logfire handles it.
13. Do not add Alembic — DDL direct is enough here.
14. Do not create a Pydantic AI example or helper module — it's listed as a
    dep but not used until a later WP.

---

## Execution order (summary)

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → **13 (gate)** → 14 → 15 → 16 → 17.

End of plan. Awaiting author confirmation before Phase 3.
