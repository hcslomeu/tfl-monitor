# TM-000 — Contracts and Scaffold

> **Role for Claude Code:** you are a senior data/AI engineer setting up the foundational scaffold and contracts for **tfl-monitor**. This is the only sequential WP — every other WP runs in parallel (max 2 at a time) from here. **Correctness and completeness of contracts is the single most important output.**
>
> Read this document fully before writing any code. Respond in Brazilian Portuguese (code in English — see `CLAUDE.md`).

---

## 1. Project context

**tfl-monitor** is a standalone portfolio project. Streaming ingestion from the TfL API → PostgreSQL modelled with dbt → RAG over TfL documents → LangGraph agent → Next.js dashboard. Deployed on Railway + Vercel + Supabase + Redpanda Cloud + Pinecone.

**This is NOT part of the existing monorepo.** Copy patterns if you know them; do not import.

---

## 2. Guiding principle: lean by default

This WP produces a **minimal functional scaffold, not a work of art**. If you catch yourself adding something not explicitly requested, stop and question it.

**Explicitly avoid in this WP:**

- Multiple `pyproject.toml`
- Makefile with more than ~15 targets
- Hierarchical Pydantic settings
- Typer/Click CLIs
- Custom structured logging (Logfire handles this in later WPs)
- Docker sidecars (Prometheus, Grafana, etc.)
- "Just in case we need to swap" abstractions
- Helper scripts nobody asked for

**Rule:** if a file was born without the author requesting it, it probably shouldn't exist.

---

## 3. Single deliverable: scaffolded repo with frozen contracts

At the end of this WP, someone should be able to:

```bash
git clone git@github.com:hcslomeu/tfl-monitor.git
cd tfl-monitor
cp .env.example .env     # edit with real keys
make bootstrap           # install Python + Node deps
make up                  # start Postgres, Redpanda, Airflow, MinIO
uv run test              # pytest (passes, even with zero domain tests)
uv run lint              # ruff + mypy (green)
pnpm --dir web build     # Next.js builds (empty pages with placeholders)
```

No business logic. Just structure and contracts.

---

## 4. Repository layout (produce exactly this)

```
tfl-monitor/
├── README.md                         # Initial version — polished in TM-F1
├── CLAUDE.md                         # Rules for Claude Code (already exists — do not overwrite)
├── AGENTS.md                         # Rules for Codex (already exists — do not overwrite)
├── ARCHITECTURE.md                   # Diagram + narrative
├── LICENSE                           # MIT
├── Makefile                          # Max ~15 targets
├── docker-compose.yml                # Postgres, Redpanda, Airflow, MinIO
├── .env.example                      # All env vars with safe placeholders
├── .gitignore
├── .dockerignore
├── pyproject.toml                    # SINGLE — root, single workspace
├── uv.lock
│
├── contracts/
│   ├── README.md                     # "Changes here require an ADR"
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                 # Shared enums and types
│   │   ├── line_status.py
│   │   ├── arrivals.py
│   │   └── disruptions.py
│   ├── openapi.yaml                  # OpenAPI 3.1
│   ├── sql/
│   │   ├── 001_raw_tables.sql
│   │   ├── 002_reference_tables.sql
│   │   └── 003_indexes.sql
│   └── dbt_sources.yml
│
├── src/                              # ALL Python code lives here
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── tfl_client/__init__.py    # Empty — populated in TM-B1
│   │   ├── producers/__init__.py     # Empty — populated in TM-B2/TM-B4
│   │   └── consumers/__init__.py     # Empty
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI with 501 stubs for all endpoints
│   │   └── observability.py          # Logfire init — see §7.2
│   └── agent/
│       ├── __init__.py
│       ├── graph.py                  # LangGraph no-op node
│       └── observability.py          # LangSmith env var validation
│
├── tests/
│   ├── __init__.py
│   ├── fixtures/                     # Real TfL JSON, committed
│   │   ├── line_status_sample.json
│   │   ├── arrivals_sample.json
│   │   └── disruptions_sample.json
│   ├── test_contracts.py             # Validates schemas match fixtures
│   └── test_health.py                # GET /health returns 200
│
├── dbt/
│   ├── README.md
│   ├── dbt_project.yml
│   ├── profiles.yml                  # Reads from env vars
│   ├── models/
│   │   ├── staging/.gitkeep
│   │   ├── intermediate/.gitkeep
│   │   └── marts/.gitkeep
│   └── sources/
│       └── tfl.yml                   # Symlink or copy of contracts/dbt_sources.yml
│
├── airflow/
│   ├── README.md
│   ├── Dockerfile                    # For Railway deploy in TM-A5
│   ├── requirements.txt
│   └── dags/.gitkeep                 # DAGs come in TM-A2
│
├── web/                              # Next.js
│   ├── README.md                     # "Design comes from claude.design in TM-E1"
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts                # Security headers
│   ├── biome.json
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                  # Network Now — placeholder
│   │   ├── reliability/page.tsx      # Placeholder
│   │   ├── disruptions/page.tsx      # Placeholder
│   │   └── ask/page.tsx              # Placeholder
│   ├── components/ui/.gitkeep        # shadcn components installed in TM-E1
│   ├── lib/
│   │   ├── api-client.ts             # Typed fetch wrapper
│   │   ├── types.ts                  # Generated from OpenAPI
│   │   └── mocks/                    # Mock API responses — committed
│   │       ├── status-live.json
│   │       ├── reliability.json
│   │       └── disruptions-recent.json
│   └── public/.gitkeep
│
├── scripts/                          # MAX 2 scripts in this WP
│   └── fetch_tfl_samples.py          # One-shot script to populate fixtures
│
├── .claude/
│   ├── adrs/
│   │   ├── 001-redpanda-over-kafka.md
│   │   ├── 002-contracts-first.md
│   │   ├── 003-airflow-on-railway.md
│   │   └── 004-logfire-langsmith-split.md
│   ├── specs/
│   │   └── TM-000-spec.md
│   └── current-wp.md                 # Points to active WP
│
└── .github/
    ├── workflows/
    │   └── ci.yml                    # lint + test + dbt parse
    └── pull_request_template.md
```

**Critical note**: there is only **one** `pyproject.toml` at the root. Python modules (`ingestion`, `api`, `agent`) are packages inside `src/`. `uv` manages the whole workspace. No sub-workspaces.

---

## 5. Contracts (most important section)

### 5.1 Pydantic schemas (`contracts/schemas/`)

**Three topics**: `line-status`, `arrivals`, `disruptions`.

**Common requirements:**

- Pydantic v2 `BaseModel`
- `model_config = ConfigDict(frozen=True)` (immutable events)
- Typed fields with `Field(description=...)` for each
- Timestamps: `datetime` UTC, ISO 8601 serialisation
- Common envelope for every event:

```python
from typing import ClassVar, Generic, Literal, TypeVar
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

P = TypeVar("P", bound=BaseModel)


class Event(BaseModel, Generic[P]):
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(..., description="Unique event identifier (UUIDv7 preferred)")
    event_type: str = Field(..., description="Event type discriminator")
    source: Literal["tfl-unified-api"] = "tfl-unified-api"
    ingested_at: datetime = Field(..., description="UTC timestamp when ingested")
    payload: P

    TOPIC_NAME: ClassVar[str]
```

- Each top-level event defines `TOPIC_NAME: ClassVar[str]` (e.g. `"line-status"`).

**Payloads (validate against the real TfL API — Swagger at `https://api.tfl.gov.uk/`):**

- `LineStatusPayload`: `line_id`, `line_name`, `mode`, `status_severity` (int 0–20), `status_severity_description`, `reason` (opt), `valid_from`, `valid_to`
- `ArrivalPayload`: `arrival_id`, `station_id`, `station_name`, `line_id`, `platform_name`, `direction`, `destination`, `expected_arrival`, `time_to_station_seconds`, `vehicle_id` (opt)
- `DisruptionPayload`: `disruption_id`, `category`, `category_description`, `description`, `summary`, `affected_routes: list[str]`, `affected_stops: list[str]`, `closure_text`, `severity`, `created`, `last_update`

`common.py` contains: `TransportMode`, `StatusSeverity` (enum), `DisruptionCategory` (enum), useful type aliases.

**Do NOT do in this WP:**
- Elaborate factory methods
- Custom validators beyond the strict minimum (e.g. one validator ensuring `valid_to > valid_from`)
- Custom serializers

### 5.2 OpenAPI 3.1 (`contracts/openapi.yaml`)

Full endpoint spec. Each response schema mirrors the Pydantic contracts (can reference via `$ref` to generated JSON schemas, or duplicate — pick the simpler path; duplication is fine for 8 endpoints).

**Endpoints:**

```
GET  /health                                → { status, dependencies: {} }
GET  /api/v1/status/live                    → list[LineStatus]
GET  /api/v1/status/history?line_id&from&to → list[LineStatus]
GET  /api/v1/reliability/{line_id}?window   → LineReliability
GET  /api/v1/disruptions/recent?limit&mode  → list[Disruption]
GET  /api/v1/bus/{stop_id}/punctuality      → BusPunctuality
POST /api/v1/chat/stream                    → SSE (text/event-stream)
GET  /api/v1/chat/{thread_id}/history       → list[ChatMessage]
```

**Requirements:**

- Each endpoint has `operationId` matching its Python function name
- Each schema has an `example`
- Errors follow RFC 7807 (`application/problem+json`)
- CORS documented in the description

### 5.3 PostgreSQL DDL (`contracts/sql/`)

**`001_raw_tables.sql`** — `raw` schema, append-only:

```sql
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.line_status (
    event_id UUID PRIMARY KEY,
    ingested_at TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);
-- repeat for raw.arrivals and raw.disruptions
```

**`002_reference_tables.sql`** — `ref` schema:

```sql
CREATE SCHEMA IF NOT EXISTS ref;

CREATE TABLE IF NOT EXISTS ref.lines (
    line_id TEXT PRIMARY KEY,
    line_name TEXT NOT NULL,
    mode TEXT NOT NULL,
    colour_hex TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ref.stations (
    station_id TEXT PRIMARY KEY,
    station_name TEXT NOT NULL,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    zones TEXT,
    modes_served TEXT[],
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`003_indexes.sql`** — time indexes + GIN on JSONB:

```sql
CREATE INDEX IF NOT EXISTS idx_line_status_ingested_at ON raw.line_status (ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_line_status_payload_gin ON raw.line_status USING GIN (payload);
-- idem for arrivals and disruptions
```

All files idempotent. `psql -f` in numeric order must produce the full schema from an empty Postgres.

### 5.4 dbt sources (`contracts/dbt_sources.yml`)

Standalone YAML declaring each `raw.*` and `ref.*` table with descriptions and tests (`not_null` on `event_id` and `ingested_at`, `unique` on `event_id`). Copied (or symlinked) to `dbt/sources/tfl.yml`.

---

## 6. Fixtures (enable parallel work on C and E tracks)

**The key to parallelism.** Track C (dbt) builds against fixtures. Track E (frontend) builds against mocks.

**You must produce real fixtures** by calling the TfL API once during this WP. Do not fabricate data.

### 6.1 Steps

1. Register a free TfL API key at `api-portal.tfl.gov.uk`. **Do not commit the key.** Add `TFL_APP_KEY=your_key_here` to `.env.example`.
2. In `scripts/fetch_tfl_samples.py`, write a script that calls:
   - `GET /Line/Mode/tube,elizabeth-line,dlr,overground/Status` → `tests/fixtures/line_status_sample.json`
   - `GET /StopPoint/940GZZLUOXC/Arrivals` (Oxford Circus) → `arrivals_sample.json`
   - `GET /Line/Mode/tube/Disruption` → `disruptions_sample.json`
3. Run once. Commit the resulting JSON.
4. **Also** produce mock responses in `web/lib/mocks/*.json` matching the OpenAPI `example` fields. This lets the frontend render before endpoints exist.

### 6.2 `fetch_tfl_samples.py`

Simple. No CLI. No Typer:

```python
"""Fetch sample TfL API responses for use as test fixtures.

Run once:
    uv run python scripts/fetch_tfl_samples.py

Requires TFL_APP_KEY in env.
"""
import json
import os
from pathlib import Path
import httpx

# ... ~40 lines, straight to the point
```

---

## 7. Service scaffolds (skeletons only)

### 7.1 `src/api/main.py`

```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.observability import configure_observability

app = FastAPI(
    title="tfl-monitor API",
    version="0.0.1",
    description="See contracts/openapi.yaml for the full spec.",
)

configure_observability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "dependencies": {}}


# Stub for each OpenAPI endpoint:
@app.get("/api/v1/status/live")
async def status_live():
    raise HTTPException(status_code=501, detail="Not implemented — see TM-D2")

# ... idem for the remaining endpoints
```

### 7.2 `src/api/observability.py` (Logfire setup)

```python
"""Logfire configuration for the API service.

Reads LOGFIRE_TOKEN from env. If missing, Logfire runs in no-op mode
(development without observability). All production deployments must set it.
"""
import os
import logfire
from fastapi import FastAPI


def configure_observability(app: FastAPI) -> None:
    logfire.configure(
        service_name="tfl-monitor-api",
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_fastapi(app)
    logfire.instrument_httpx()
    logfire.instrument_psycopg()
```

### 7.3 `src/agent/observability.py` (LangSmith env validation)

```python
"""LangSmith configuration helper.

LangGraph and Pydantic AI pick up LANGSMITH_* env vars automatically.
This module only validates the environment and logs status.
"""
import os
import logging

logger = logging.getLogger(__name__)


def validate_langsmith_env() -> bool:
    """Return True if LangSmith is configured."""
    if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
        if not os.getenv("LANGSMITH_API_KEY"):
            logger.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is missing")
            return False
        project = os.getenv("LANGSMITH_PROJECT", "tfl-monitor")
        logger.info("LangSmith tracing enabled for project=%s", project)
        return True
    logger.info("LangSmith tracing disabled (set LANGSMITH_TRACING=true to enable)")
    return False
```

### 7.4 `src/agent/graph.py`

```python
"""Placeholder LangGraph graph. Real implementation in TM-D5."""
from langgraph.graph import StateGraph, END
from typing import TypedDict

from agent.observability import validate_langsmith_env


class AgentState(TypedDict):
    messages: list[dict]


def noop(state: AgentState) -> AgentState:
    return {"messages": state["messages"] + [{"role": "assistant", "content": "not-implemented"}]}


validate_langsmith_env()

graph = StateGraph(AgentState)
graph.add_node("noop", noop)
graph.set_entry_point("noop")
graph.add_edge("noop", END)
app = graph.compile()
```

### 7.5 Frontend scaffold

```bash
cd web
pnpm create next-app@latest . --ts --app --tailwind --import-alias "@/*" --no-eslint
pnpm add -D @biomejs/biome
pnpm biome init
pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add button card tabs badge skeleton alert
```

Each page renders a simple Card: `<Card><CardHeader>Network Now</CardHeader><CardContent>Coming in TM-E1</CardContent></Card>`.

`lib/api-client.ts`: ~30-line typed fetch wrapper. Uses `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

`lib/types.ts`: generated via `npx openapi-typescript ../contracts/openapi.yaml -o lib/types.ts`. Committed in this WP.

`next.config.ts`: security headers configured.

---

## 8. Docker Compose

Minimal. Only:

- `postgres` (Postgres 16, healthcheck, persistent volume, mounts `contracts/sql/` at `/docker-entrypoint-initdb.d/`)
- `redpanda` (single-node, healthcheck)
- `redpanda-console` (UI on :8080)
- `airflow-init` + `airflow-webserver` + `airflow-scheduler` (LocalExecutor, uses Postgres as metadata DB)
- `minio` (local S3 for RAG PDFs and Airflow artefacts)

**Ports:**

| Service | Port |
|---|---|
| Postgres | 5432 |
| Redpanda (Kafka) | 9092 |
| Redpanda Console | 8080 |
| Airflow | 8082 |
| MinIO API | 9000 |
| MinIO Console | 9001 |

FastAPI (:8000) and Next.js (:3000) run locally **outside** Compose during dev (`uvicorn`, `pnpm dev`).

All healthchecks must pass within 90s. `restart: unless-stopped`.

---

## 9. `pyproject.toml` (single, at root)

```toml
[project]
name = "tfl-monitor"
version = "0.0.1"
description = "Real-time data platform for TfL (Transport for London)"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sse-starlette>=2.1",
    "httpx>=0.28",
    "pydantic>=2.9",
    "pydantic-ai>=0.0.14",
    "pydantic-settings>=2.6",
    "aiokafka>=0.12",
    "psycopg[binary]>=3.2",
    "langgraph>=1.0",
    "langsmith>=0.1",
    "llama-index>=0.12",
    "pinecone>=5.0",
    "docling>=2.0",
    "anthropic>=0.39",
    "openai>=1.54",
    "logfire[fastapi,httpx,psycopg]>=3.0",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "mypy>=1.13",
    "bandit>=1.7",
    "dbt-core>=1.9",
    "dbt-postgres>=1.9",
    "openapi-spec-validator>=0.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ingestion", "src/api", "src/agent"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
exclude = ["scripts/"]

[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"

[tool.uv.scripts]
test = "pytest"
lint = "bash -c 'ruff check . && ruff format --check . && mypy src'"
fmt = "bash -c 'ruff check --fix . && ruff format .'"
dbt-parse = "dbt parse --project-dir dbt --profiles-dir dbt"
api = "uvicorn api.main:app --reload --app-dir src"
```

**Note:** `[tool.uv.scripts]` is uv's task runner. Invoke with `uv run test`, `uv run lint`, etc. **No Invoke, no Taskfile, no justfile.**

---

## 10. Makefile (short orchestrator)

```makefile
.PHONY: help bootstrap up down clean check seed openapi-ts

help:
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install Python + Node deps; create .env
	@uv --version >/dev/null 2>&1 || { echo "uv not installed. See https://docs.astral.sh/uv/"; exit 1; }
	@pnpm --version >/dev/null 2>&1 || { echo "pnpm not installed. See https://pnpm.io/"; exit 1; }
	uv sync
	pnpm --dir web install
	@test -f .env || cp .env.example .env
	@echo "Bootstrap complete. Edit .env and run 'make up'."

up: ## Start Docker Compose (Postgres, Redpanda, Airflow, MinIO)
	docker compose up -d
	@echo "Waiting for healthchecks..."
	@docker compose ps

down: ## Stop Docker Compose (preserves volumes)
	docker compose down

clean: ## Remove Docker Compose + volumes (destructive)
	docker compose down -v

check: ## Lint + Python tests + TS build
	uv run lint
	uv run test
	pnpm --dir web lint
	pnpm --dir web build

seed: ## Load fixtures into local Postgres
	uv run python scripts/seed_fixtures.py

openapi-ts: ## Regenerate TS types from OpenAPI
	pnpm --dir web exec openapi-typescript ../contracts/openapi.yaml -o lib/types.ts
```

~12 useful targets, nothing superfluous.

---

## 11. `.env.example` (complete set)

```bash
# TfL API — get a free key at api-portal.tfl.gov.uk
TFL_APP_KEY=your_tfl_key_here

# Local Postgres (dev)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=tflmonitor
POSTGRES_PASSWORD=change_me
POSTGRES_DB=tflmonitor

# Kafka (Redpanda) — local defaults work in docker-compose
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_SECURITY_PROTOCOL=PLAINTEXT
KAFKA_SASL_MECHANISM=
KAFKA_SASL_USERNAME=
KAFKA_SASL_PASSWORD=

# LLMs
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Vector DB
PINECONE_API_KEY=pcsk-...
PINECONE_INDEX=tfl-monitor

# LangSmith observability
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=ls-...
LANGSMITH_PROJECT=tfl-monitor

# Logfire observability
LOGFIRE_TOKEN=pylf_v1_...

# Environment tag for observability
ENVIRONMENT=local
APP_VERSION=0.0.1
```

---

## 12. Security (from day zero)

- `.env` in `.gitignore`. `.env.example` with placeholders.
- No hardcoded secrets.
- CORS allowlist via env var.
- Postgres: SCRAM-SHA-256.
- `bandit -r src/` in CI, blocks on HIGH severity.
- Next.js `next.config.ts`:

```typescript
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

export default {
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};
```

---

## 13. CI (`.github/workflows/ci.yml`)

Minimal but real. Runs on every PR:

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  python:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: --health-cmd="pg_isready" --health-interval=10s
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run lint
      - run: uv run test
      - run: uv run bandit -r src --severity-level high
      - run: uv run dbt-parse
        env:
          POSTGRES_HOST: localhost

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: web/pnpm-lock.yaml
      - run: pnpm --dir web install
      - run: pnpm --dir web lint
      - run: pnpm --dir web build
```

---

## 14. ADRs to write (short, ~1 page each)

In `.claude/adrs/`:

1. **001 — Redpanda over vanilla Kafka**: API-compatible, single binary, same code in dev and Redpanda Cloud.
2. **002 — Contracts-first parallelism**: why `contracts/` exists, how it changes.
3. **003 — Airflow on Railway in production**: ~£5/mo, portfolio signal, single source of scheduling.
4. **004 — Logfire for app + LangSmith for LLM**: clear split of concerns, both hosted free tiers, no self-hosted observability stack.

**Do NOT write more ADRs in this WP.** If a need arises, document it in the PR and defer.

---

## 15. PR template (`.github/pull_request_template.md`)

```markdown
## WP
<!-- e.g. TM-B2 -->

## Summary
<!-- 2–3 sentences in PT-BR -->

## Directories touched
<!-- Must stay within the WP's track. Reviewer rejects if it crosses tracks. -->

## Contracts changed?
- [ ] No
- [ ] Yes — ADR: <link>

## Checklist
- [ ] `uv run lint` passes
- [ ] `uv run test` passes
- [ ] New files or deps justified
- [ ] Linear issue updated
```

---

## 16. Acceptance criteria

This WP is DONE when:

- [ ] Fresh clone + `make bootstrap` + `make up` works on a machine with only Docker, uv, pnpm, git installed
- [ ] `uv run test` passes
- [ ] `uv run lint` passes clean
- [ ] `pnpm --dir web build` passes clean
- [ ] All files from §4 exist (or `.gitkeep` where indicated)
- [ ] `from contracts.schemas import LineStatusEvent, ArrivalEvent, DisruptionEvent` works
- [ ] `contracts/openapi.yaml` validates (`openapi-spec-validator` passes)
- [ ] DDL runs clean against empty Postgres 16
- [ ] Real TfL fixtures committed in `tests/fixtures/`
- [ ] API mocks in `web/lib/mocks/`
- [ ] 4 ADRs written
- [ ] `ARCHITECTURE.md` written
- [ ] `README.md` written (initial version; polished in TM-F1)
- [ ] CI green on the PR
- [ ] `contracts/README.md` explicitly says: "Changes here require an ADR and a broadcast."
- [ ] `PROGRESS.md` created with TM-000 marked ✅
- [ ] `src/api/observability.py` + `src/agent/observability.py` exist and are imported by the entrypoints (even though they're no-ops without tokens — the wiring is what matters)

---

## 17. What you should NOT do in this WP

- Do not implement TfL client methods beyond the fixture script
- Do not write dbt models (scaffold only)
- Do not write Airflow DAGs (empty `dags/` directory)
- Do not implement the LangGraph agent beyond the no-op
- Do not implement FastAPI endpoints (all return 501)
- Do not install RAG deps beyond what's in `pyproject.toml` — do not use them
- Do not deploy
- Do not create authentication
- Do not build real frontend views (placeholder Cards "Coming in TM-EX")
- Do not create a `generate_ts_types.sh` — use `make openapi-ts` directly
- Do not write end-to-end integration tests
- Do not add Prometheus/Grafana/OTel collector stacks — Logfire handles it
- Do not add Alembic — DDL direct is enough here
- Do not create a Pydantic AI example or helper module — it's listed as a dep but not used until a later WP

---

## 18. Suggested execution order

1. Create directory tree, `.gitignore`, empty files
2. `pyproject.toml` + `uv sync`
3. `contracts/schemas/*.py` — most important output
4. `contracts/openapi.yaml`
5. `contracts/sql/*.sql`
6. `contracts/dbt_sources.yml`
7. `scripts/fetch_tfl_samples.py` + run + commit fixtures
8. `web/lib/mocks/*.json` derived from OpenAPI examples
9. `docker-compose.yml`
10. `Makefile`
11. Service scaffolds (`src/api/main.py` with 501s, `src/api/observability.py`, `src/agent/graph.py` no-op, `src/agent/observability.py`)
12. Frontend scaffold with placeholders
13. `.github/workflows/ci.yml`
14. 4 ADRs, `ARCHITECTURE.md`, `README.md`, `PROGRESS.md`
15. `make bootstrap`, `make up`, `make check` — all green
16. Open PR

---

## 19. When to ask the author

- The TfL API returns a schema that contradicts §5.1 — adjust the schema and document
- A library in §9 has a breaking issue (e.g. LangGraph 1.x incompatibility) — flag it, do not silently substitute
- Any criterion in §16 seems impossible in <5h — say so upfront

Otherwise, proceed.
