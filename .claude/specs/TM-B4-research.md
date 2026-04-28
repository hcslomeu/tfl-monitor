# TM-B4 — Research (Phase 1)

Read-only survey of the codebase before planning the arrivals + disruptions
producers/consumers. Acceptance criteria from `SETUP.md` §7.3:

> Add producers and consumers for the two remaining topics (arrivals,
> disruptions).

Linear: TM-12.

---

## 1. Existing pieces ready to consume

### 1.1 Pydantic event contracts (frozen — no edits this WP)

- `contracts/schemas/arrivals.py`
  - `ArrivalPayload` (frozen): `arrival_id`, `station_id`, `station_name`,
    `line_id`, `platform_name`, `direction`, `destination`,
    `expected_arrival`, `time_to_station_seconds`, `vehicle_id?`.
  - `ArrivalEvent(Event[ArrivalPayload])`,
    `TOPIC_NAME = "arrivals"`.
- `contracts/schemas/disruptions.py`
  - `DisruptionPayload` (frozen): `disruption_id`, `category`,
    `category_description`, `description`, `summary`, `affected_routes`,
    `affected_stops`, `closure_text`, `severity`, `created`,
    `last_update`.
  - `DisruptionEvent(Event[DisruptionPayload])`,
    `TOPIC_NAME = "disruptions"`.
- `contracts/schemas/common.py:67-86`
  - Generic `Event[P]` envelope: `event_id`, `event_type`, `source`,
    `ingested_at`, `payload`. All three topic events derive from this.

### 1.2 Tier-1 → tier-2 normalisers (frozen — already used by TM-B1)

- `src/ingestion/tfl_client/normalise.py`
  - `arrival_payloads(list[TflArrivalPrediction]) -> list[ArrivalPayload]`
  - `disruption_payloads(list[TflDisruption]) -> list[DisruptionPayload]`
  - Synthesises stable `disruption_id` via SHA-256 over
    `(category, type, closure_text, description.strip(), sorted(affected_routes))`.
  - Synthesises `created` / `last_update` to `now()` (TfL's free
    `/Disruption` endpoint omits stable ids and timestamps).

### 1.3 TfL async client (frozen)

- `src/ingestion/tfl_client/client.py`
  - `TflClient.fetch_arrivals(stop_id) -> list[TflArrivalPrediction]`
    via `GET /StopPoint/{stop_id}/Arrivals`. **Per-stop call** — needs
    a list of NaPTAN ids from the producer.
  - `TflClient.fetch_disruptions(modes) -> list[TflDisruption]` via
    `GET /Line/Mode/{modes}/Disruption`. Single call per cycle.
  - Same `app_key` redaction + hand-rolled retry as line-status.
  - `TflClient.from_env()` reads `TFL_APP_KEY`.

### 1.4 Test fixtures

- `tests/fixtures/tfl/arrivals_oxford_circus.json` (~17 KB) —
  raw `/StopPoint/940GZZLUOXC/Arrivals` response.
- `tests/fixtures/tfl/disruptions_tube.json` (~7 KB) —
  raw `/Line/Mode/tube/Disruption` response.
- `tests/ingestion/conftest.py:33-39` exposes both fixtures as
  pytest fixtures: `arrivals_oxford_circus_fixture`,
  `disruptions_tube_fixture`.

### 1.5 Raw Postgres tables (frozen — DDL identical for all three)

- `contracts/sql/001_raw_tables.sql:24-46` declares
  `raw.arrivals` and `raw.disruptions` with the same envelope columns
  as `raw.line_status`:
  ```sql
  event_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type TEXT NOT NULL,
  source     TEXT NOT NULL,
  payload    JSONB NOT NULL
  ```
- Loaded into the `postgres` Compose service via
  `/docker-entrypoint-initdb.d` mount.

### 1.6 Producer / consumer infrastructure built by TM-B2 + TM-B3

- `src/ingestion/producers/kafka.py` —
  `KafkaEventProducer` is **already topic-agnostic** (takes a `topic`
  arg + any Pydantic `BaseModel`). Reusable as-is.
- `src/ingestion/consumers/kafka.py` —
  `KafkaEventConsumer` is **already topic-agnostic** (takes a `topic`
  positional arg, configurable `client_id`/`group_id`/
  `auto_offset_reset`). Reusable as-is.
- `src/ingestion/observability.py` —
  `configure_logfire(instrument_psycopg=...)` shared helper. Reusable
  as-is.
- `src/ingestion/producers/line_status.py` —
  pattern to mirror for new producers (`run_once` + `run_forever`
  fixed-rate cadence, fail-soft logging, deterministic
  `clock` + `event_id_factory` injection points for tests).
- `src/ingestion/consumers/line_status.py` —
  pattern to mirror or generalise for new consumers (loop with
  poison-pill skip+commit, OperationalError reconnect+replay,
  unknown-error replay, lag-tracing every 50 msgs / 30 s).
- `src/ingestion/consumers/postgres.py` —
  `RawLineStatusWriter` is **line-status-specific** in two places:
  the SQL string hard-codes `raw.line_status` and the `insert`
  signature accepts `LineStatusEvent`. Otherwise the body is
  topic-agnostic (writes the 5-column envelope, JSONB payload,
  `ON CONFLICT (event_id) DO NOTHING`).

### 1.7 Compose stack (touched by TM-B2 + TM-B3)

- `docker-compose.yml:57-72` —
  `redpanda-init` (profile `init`) currently creates only
  `line-status` topic with `--partitions 1 --replicas 1`. Idempotent
  (`already exists` is treated as success).
- `docker-compose.yml:74-89` —
  `tfl-line-status-producer` service (profile `ingest`).
- `docker-compose.yml:91-108` —
  `tfl-line-status-consumer` service (profile `ingest`).
- `src/ingestion/Dockerfile` is generic (runs `uv run python -m
  ingestion.<...>`), so new services can reuse it with a different
  `command:` array.

### 1.8 Wiring (Make + taskipy)

- `pyproject.toml` `[tool.taskipy.tasks]` exposes
  `ingest-line-status` and `consume-line-status`. Two new equivalents
  per topic land here (`ingest-arrivals`, `ingest-disruptions`,
  `consume-arrivals`, `consume-disruptions`).
- `Makefile` exposes `consume-line-status` only (the producer is
  expected to run via Compose, not via `make`). Mirror that pattern:
  add `consume-arrivals`, `consume-disruptions` if useful, but the
  producer-side make targets are optional (Compose covers the
  prod-like path).
- `init-topics` task (`docker compose --profile init up
  redpanda-init`) needs to create `arrivals` + `disruptions` too —
  one-line additions inside the `redpanda-init` shell script.

---

## 2. Pieces missing — what TM-B4 adds

### 2.1 Producers (two)

- `src/ingestion/producers/arrivals.py`
  - Polls `TflClient.fetch_arrivals(stop_id)` for a fixed list of
    NaPTAN stop ids; normalises via `arrival_payloads`; wraps in
    `ArrivalEvent` envelope; publishes to topic `"arrivals"`.
  - Cadence + stop list: see §3 open questions below.
- `src/ingestion/producers/disruptions.py`
  - Polls `TflClient.fetch_disruptions(modes)`; normalises via
    `disruption_payloads`; wraps in `DisruptionEvent`; publishes to
    topic `"disruptions"`.
  - Cadence + modes: see §3 open questions.

### 2.2 Consumers (two)

- `src/ingestion/consumers/arrivals.py` — entrypoint over the
  generic event consumer (see §2.3).
- `src/ingestion/consumers/disruptions.py` — entrypoint over the
  generic event consumer.

### 2.3 Generic consumer + writer (refactor of TM-B3 surfaces)

CLAUDE.md "Principle #1" rule 4: abstract when the second case
arrives. We now have three topics, so the consumer body — currently
hard-coded to `LineStatusEvent` and `raw.line_status` — earns
generalisation:

- `src/ingestion/consumers/postgres.py`
  - Replace `RawLineStatusWriter` with a parameterised
    `RawEventWriter(dsn, table_name, event_class)` — body otherwise
    identical (5-column envelope, `Jsonb(payload)`, `ON CONFLICT DO
    NOTHING`, reconnect-on-`OperationalError`).
- `src/ingestion/consumers/event_consumer.py` (new)
  - Generic `RawEventConsumer[E: Event[Any]]` parameterised on the
    event class to validate against. The poll loop / poison-pill
    skip+commit / replay-on-failure / lag-refresh logic is the same
    across all three topics.
- `src/ingestion/consumers/line_status.py`
  - Becomes a thin entrypoint that wires
    `RawEventConsumer[LineStatusEvent]` + `RawEventWriter("raw.line_status",
    LineStatusEvent)` — preserves `python -m
    ingestion.consumers.line_status` invocation contract.

### 2.4 Topic provisioning

- `docker-compose.yml` `redpanda-init` command extended to create the
  three topics (`line-status`, `arrivals`, `disruptions`). Same
  `--partitions 1 --replicas 1` for local dev.

### 2.5 Compose services (four new)

- `tfl-arrivals-producer` (profile `ingest`)
- `tfl-arrivals-consumer` (profile `ingest`)
- `tfl-disruptions-producer` (profile `ingest`)
- `tfl-disruptions-consumer` (profile `ingest`)

All build from the existing `src/ingestion/Dockerfile`. Differ only
in `command:` array.

### 2.6 Tests

- `tests/ingestion/test_arrivals_producer.py` — mirror of
  `test_line_status_producer.py`, using `arrivals_oxford_circus_fixture`.
- `tests/ingestion/test_disruptions_producer.py` — mirror, using
  `disruptions_tube_fixture`.
- `tests/ingestion/test_event_consumer.py` — generic consumer tests
  (parametrised over `LineStatusEvent`, `ArrivalEvent`,
  `DisruptionEvent`). Replaces `test_line_status_consumer.py`
  scenarios while preserving coverage. Alternatively add per-topic
  consumer test files; decision in plan.
- `tests/ingestion/test_postgres_writer.py` — adapt existing tests
  to the new `RawEventWriter` signature; reuse existing fakes.
- `tests/ingestion/integration/` — extend smoke tests to cover the
  new topics (one-shot per-topic, gated on `KAFKA_BOOTSTRAP_SERVERS`
  + `DATABASE_URL`).

### 2.7 Wiring

- `pyproject.toml` `[tool.taskipy.tasks]` adds four entries
  (`ingest-arrivals`, `ingest-disruptions`, `consume-arrivals`,
  `consume-disruptions`).
- `Makefile` adds `consume-arrivals` + `consume-disruptions`
  (mirroring `consume-line-status`).
- `PROGRESS.md` — flip TM-B4 row to ✅ on the date.

---

## 3. Open questions to resolve in the plan

### Q1 — Stop list for arrivals

`fetch_arrivals` is per-stop. We need a finite list of NaPTAN stop
ids to poll on each cycle. Options:

- **Q1a — Single fixture-aligned stop**: just Oxford Circus
  (`940GZZLUOXC`). Smallest blast radius, easiest tests.
- **Q1b — Major-hub list (5)**: Oxford Circus, King's Cross
  St Pancras (`940GZZLUKSX`), Waterloo (`940GZZLUWLO`), Bank
  (`940GZZLUBNK`), Liverpool Street (`940GZZLULVT`). Demonstrates
  multi-stop fan-out for the portfolio narrative; still well within
  TfL's 500/min budget.
- **Q1c — Dynamic discovery from `/Line/<line>/Route/Sequence/...`**:
  full coverage but adds an additional TfL endpoint, schema, and
  fixture. Out of scope for a prototype WP.

**Recommended default: Q1b**, exposed as a module-level constant
`DEFAULT_ARRIVAL_STOPS` so tests can override with a single stop.

### Q2 — Modes for disruptions

`fetch_disruptions` takes the same modes argument as
`fetch_line_statuses`. The line-status producer uses
`("tube", "elizabeth-line", "overground", "dlr")`.

- **Q2a — Reuse the same four modes** (recommended: parity with
  line-status). Single TfL request per cycle.
- **Q2b — Add `bus`** (large payload, hits 500/min faster). Defer
  to a follow-up if the bus-related dashboard story arrives.

**Recommended default: Q2a**, expose as
`DEFAULT_DISRUPTION_MODES`.

### Q3 — Poll cadence

- **Arrivals**: TfL refresh ≈ 30 s. Polling 5 stops × every 30 s = 10
  HTTP calls/min. Safe under 500/min.
  - **Q3a — 30 s** (recommended: matches upstream refresh).
  - Q3b — 60 s (lighter on TfL but loses freshness).
- **Disruptions**: low-frequency change.
  - **Q3c — 300 s** (recommended: 5 minutes; one TfL call every
    5 min × 4 modes = trivial budget).
  - Q3d — 60 s (overkill for a slow-moving dataset).

**Recommended defaults: Q3a + Q3c**, exposed as
`ARRIVALS_POLL_PERIOD_SECONDS = 30.0` and
`DISRUPTIONS_POLL_PERIOD_SECONDS = 300.0`.

### Q4 — Partition keys

- **Arrivals**: `payload.station_id` (recommended) — keeps per-stop
  ordering useful for the dashboard. Alternatives: `arrival_id`
  (over-partitions, no ordering benefit), `line_id` (concentrates
  many stops on a few partitions).
- **Disruptions**: `payload.disruption_id` (synthetic SHA-256,
  recommended) — uniform distribution; no ordering benefit since
  events are independent.

### Q5 — Consumer + writer generalisation

Three options:

- **Q5a — Full generic** (recommended): introduce
  `RawEventConsumer[E]` + `RawEventWriter(table, event_class)`,
  migrate line-status. Single source of truth for the loop logic;
  matches CLAUDE.md "Principle #1" rule 4.
- Q5b — Duplicate three near-identical 200-line consumer modules.
  Violates DRY; adds maintenance debt.
- Q5c — Inheritance with `LineStatusConsumer` as base. Confusing
  hierarchy; mid-step compromise.

**Recommended default: Q5a.**

### Q6 — Event-type discriminators

Existing line-status events use
`event_type = "line-status.snapshot"`. Mirror:

- **Arrivals**: `"arrivals.snapshot"` (recommended).
- **Disruptions**: `"disruptions.snapshot"` (recommended).

### Q7 — Consumer group ids

- **Q7a — Per-topic writer groups** (recommended): match TM-B3 style.
  - `tfl-monitor-arrivals-writer`
  - `tfl-monitor-disruptions-writer`
  - `tfl-monitor-line-status-writer` (already in production)

### Q8 — Test layout

- **Q8a — Per-topic producer test files** + **single generic
  consumer test file** (recommended): producers differ enough
  (different fixtures, different fetch shape) to justify separate
  files; consumers are uniform via `RawEventConsumer`, so a single
  parametrised file is cleanest.
- Q8b — Per-topic consumer files. More files, identical bodies.
- Q8c — Single mega-file. Loses readability.

### Q9 — Compose service count

Four new services or two combined producer+consumer services?

- **Q9a — Four services** (recommended): one producer + one
  consumer per topic. Matches TM-B3's pattern; lets the author
  scale them independently for prod (TM-A5).
- Q9b — Combined. Mixes lifecycles; not how Kafka is typically
  deployed.

### Q10 — Idempotency

All three writers use `INSERT … ON CONFLICT (event_id) DO NOTHING`,
so cross-PR replays are safe at the SQL level. Synthesis:
- Arrivals — UUIDv4 `event_id` per cycle. Replays produce identical
  rows except for `event_id`, so duplicates **will** land if the
  same `arrival_id` shows up in two cycles. This is acceptable for
  the prototype (the dashboard will dedupe by `(arrival_id,
  station_id)` in dbt).
- Disruptions — synthetic `disruption_id` is stable across cycles
  by §1.2; envelope `event_id` is fresh per cycle. Same dedup story
  in dbt.
- Line-status — same.

No change required. Document the dbt-side dedup expectation in the
plan's "What we're NOT doing" section so TM-C2/C3 know to absorb it.

### Q11 — Per-stop fan-out concurrency

Sequential vs concurrent stop calls? For 5 stops × 30 s cycle, even
sequential leaves >25 s of headroom on a typical TfL p95 of <1 s.

- **Q11a — Sequential** (recommended): simpler error handling, easy
  retry semantics, no asyncio.gather error aggregation.
- Q11b — Concurrent (`asyncio.gather`). Premature optimisation for
  the prototype.

### Q12 — `.env.example` parity

`docker-compose.yml` substitutes `DATABASE_URL` from
`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` for the consumer
services. No new env var required — the Compose services inherit
the existing pattern.

---

## 4. Risk and constraints

- **CLAUDE.md "Principle #1" rule 4** — abstract on the second case.
  TM-B3 deliberately did not generalise (one consumer); TM-B4 lands
  the third. Generalisation is now the lean path; further duplication
  would be the over-engineering choice.
- **Frozen contracts** — `contracts/schemas/*` and `contracts/sql/*`
  must not be edited (CLAUDE.md "WP scope rules" #2 + AGENTS.md
  track inventory). All event shapes + raw DDL are already correct.
- **`.env.example`** — `TFL_APP_KEY` already required by the existing
  `tfl-line-status-producer` Compose service (`?:?TFL_APP_KEY is
  required`); reuse the pattern verbatim.
- **Mypy strict** — every new signature must be fully annotated. The
  generic `RawEventConsumer[E]` needs a `TypeVar` bound to `Event[Any]`.
  Same for `RawEventWriter`.
- **Tests must continue to pass on `make check`**. The line-status
  consumer test file's whitebox `_cached_lag` assertion needs to
  survive the rename (or be replaced when generalising).
- **No new runtime deps** — `aiokafka`, `psycopg[binary]`,
  `pydantic`, `logfire`, `httpx` already cover the surface.

---

## 5. References

- `.claude/specs/TM-B2-plan.md` — producer template (Phase 3.2).
- `.claude/specs/TM-B3-plan.md` — consumer template (Phase 3.4) +
  observability extraction precedent (Phase 3.1).
- `CLAUDE.md` — §"Principle #1: lean by default" rules 4, 5, 6;
  §"Pydantic usage conventions"; §"Phase approach".
- `AGENTS.md` — track inventory, review checklist.
- `contracts/schemas/{arrivals,disruptions,common}.py` — frozen
  Pydantic shapes consumed verbatim.
- `contracts/sql/001_raw_tables.sql` — `raw.arrivals`,
  `raw.disruptions` DDL.
- `src/ingestion/tfl_client/` — `fetch_arrivals`,
  `fetch_disruptions`, `arrival_payloads`, `disruption_payloads`.
- `tests/fixtures/tfl/{arrivals_oxford_circus,disruptions_tube}.json`
  — committed by TM-B1.
- `docker-compose.yml:57-108` — existing `redpanda-init` +
  line-status producer/consumer services to mirror.
