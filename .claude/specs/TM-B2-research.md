# TM-B2 — Phase 1 research (read-only)

Source: AGENTS.md §"Track inventory" + SETUP.md §"WP catalogue" row TM-B2.
Date: 2026-04-27.
Active WP: TM-B2 — `line-status` producer to Kafka (track `B-ingestion`,
phase 3, depends on TM-A1 + TM-B1).

This document is a **read-only audit** of the current code, contracts,
and infra relevant to TM-B2. It does not propose an implementation.
Open questions are surfaced for Phase 2 to resolve with the author.

## 1. Stated objective and acceptance criteria

SETUP.md row TM-B2: *"Poll line-status every 30s and publish validated
events to Kafka."* No expanded spec block exists for TM-B2 in SETUP.md
(the WP catalogue lists only the one-line objective; expanded specs were
written ad-hoc per WP under `.claude/specs/`).

Implicit acceptance criteria, derived from upstream WPs and from
AGENTS.md §1 + §2:

- The producer must call `TflClient.fetch_line_statuses(...)` (TM-B1
  surface) on a fixed cadence (the catalogue says "every 30s").
- Each tier-1 response must be normalised via
  `ingestion.tfl_client.normalise.line_status_payloads` into a list of
  `LineStatusPayload`.
- Each `LineStatusPayload` must be wrapped in a `LineStatusEvent`
  envelope (`event_id`, `event_type`, `source`, `ingested_at`,
  `payload`) and published to topic `LineStatusEvent.TOPIC_NAME =
  "line-status"`.
- Events must reach Redpanda intact, validated against the tier-2
  Pydantic contract (`LineStatusPayload` is `frozen=True`, has a
  validity-window invariant; the envelope `Event` is also frozen).
- Failures (TfL transient errors, Kafka transient errors) must not
  crash the producer loop; they must be logged via Logfire and the
  next cycle must run.
- Track scope: only `src/ingestion/`, `tests/ingestion/`, plus producer
  config and topic creation in `docker-compose.yml` if absolutely
  necessary. **No edits to `contracts/`** (CLAUDE.md "Principle #1"
  + AGENTS.md §1).
- `aiokafka` is the only Kafka client allowed (locked in
  `pyproject.toml`, ADR 001).

## 2. Existing ingestion surface

### `src/ingestion/`

```
src/ingestion/
├── __init__.py            (empty marker)
├── consumers/             (empty package; reserved for TM-B3)
│   └── __init__.py
├── producers/             (empty package; reserved for TM-B2)
│   └── __init__.py
└── tfl_client/            (TM-B1, complete)
    ├── __init__.py        re-exports TflClient + 3 normalisers
    ├── client.py          async TfL HTTP client + Logfire span + redaction
    ├── normalise.py       tier-1 → tier-2 pure adapters
    └── retry.py           hand-rolled retry helper (RFC 9110 Retry-After)
```

The `producers/` package exists as an empty `__init__.py` placeholder.
No producer code is in flight.

### TfL client surface relevant to TM-B2

`TflClient.fetch_line_statuses(modes: Iterable[str]) -> list[TflLineResponse]`
(`src/ingestion/tfl_client/client.py:85`). Async, runs inside an
`async with TflClient(app_key=...)` block, returns tier-1 typed models.
Constructor reads `TFL_APP_KEY` directly (`from_env()` classmethod);
`Settings(BaseSettings)` is intentionally not used (CLAUDE.md "Principle
#1" rule 5).

### Normalisation entry point

`ingestion.tfl_client.normalise.line_status_payloads(response) ->
list[LineStatusPayload]`
(`src/ingestion/tfl_client/normalise.py:43`). Pure function, no I/O.
Flattens `lineStatuses[*].validityPeriods[*]` into one payload per
validity window; falls back to a 12h window when validity periods are
missing (matches `test_contracts.py` convention). Skips lines whose
`mode_name` does not map to a `TransportMode` enum value, emitting
`logfire.warn("tfl.normalise.unknown_transport_mode", ...)`. Wrapping
into `LineStatusEvent` is **explicitly delegated to producers**
(`normalise.py:8-12` docstring).

## 3. Tier-2 wire format

`contracts/schemas/line_status.py:13-39`:

- `LineStatusPayload` — frozen Pydantic v2 model, fields: `line_id`,
  `line_name`, `mode: TransportMode`, `status_severity` (0..20),
  `status_severity_description`, `reason: str | None`, `valid_from`,
  `valid_to`. Model validator enforces `valid_to > valid_from`.
- `LineStatusEvent(Event[LineStatusPayload])` — `TOPIC_NAME =
  "line-status"`.

`contracts/schemas/common.py:67-86` `Event[P]` envelope — frozen,
fields: `event_id: UUID` (UUIDv7 *preferred*, type `UUID`), `event_type:
str`, `source: Literal["tfl-unified-api"] = "tfl-unified-api"`,
`ingested_at: datetime`, `payload: P`. The `event_type` discriminator is
free-form `str` — TM-B2 must pick a value (no constant exists; see open
question Q3).

Pydantic JSON serialisation of these models is the canonical wire
format (CLAUDE.md §"Pydantic usage conventions" — "Kafka events:
`contracts/schemas/*.py` — frozen Pydantic models, JSON-serialised on
wire").

## 4. Topic / broker substrate (TM-A1)

`docker-compose.yml:22-43`:

- Service `redpanda` (image `redpandadata/redpanda:v24.2.7`), single
  broker, `--mode=dev-container --smp=1`.
- Listeners: internal `redpanda:9092`, external `localhost:19092`.
- Healthcheck: `rpk cluster info`.
- `redpanda-console` (image `redpandadata/console:v2.7.2`) under
  `profiles: ["ui"]` at `:8080`.
- Persistent volume `redpanda-data:/var/lib/redpanda/data`.

No topic is pre-created in the Compose file. Redpanda's
`auto.create.topics.enable` defaults to `true` in `--mode=dev-container`,
so a producer that writes to a non-existent topic will see it created
on demand (single partition, default replication factor 1 in dev).

`.env.example:13-17` already declares the Kafka surface:

```env
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
KAFKA_SECURITY_PROTOCOL=PLAINTEXT
KAFKA_SASL_MECHANISM=
KAFKA_SASL_USERNAME=
KAFKA_SASL_PASSWORD=
```

The SASL fields are placeholders for the Redpanda Cloud migration
(TM-A4); local dev runs `PLAINTEXT`.

## 5. Consumer / warehouse contract (TM-B3 / TM-C2 — downstream)

`contracts/sql/001_raw_tables.sql:12-22`:

```sql
CREATE TABLE raw.line_status (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);
```

The raw schema preserves the envelope verbatim. `event_id` is the
primary key — duplicates from at-least-once delivery will be rejected
by the consumer (TM-B3) on insert; the producer can pick any stable
unique value. `payload JSONB` carries the tier-2 `LineStatusPayload`
serialised by Pydantic.

This is informational only — TM-B2 does not write to Postgres.

## 6. Dependencies and tooling

`pyproject.toml`:

- `aiokafka>=0.12` already present (line 14).
- `pydantic>=2.9`, `logfire[fastapi,httpx,psycopg]>=3.0` — both used
  by the existing TfL client.
- `pytest-asyncio>=0.24` with `asyncio_mode = "auto"` (line 61) —
  async tests run without explicit decorators.
- `pythonpath = ["src"]` (line 60) — imports use
  `from ingestion.foo import X` (no `src.` prefix; napkin Domain#3).
- `[tool.mypy] strict = true` — every signature must be fully typed.

`tests/ingestion/conftest.py:1-71` — fixtures:
`line_status_tube_fixture`, `line_status_multi_mode_fixture`,
`make_transport`, `script_responses`. The `httpx.MockTransport` pattern
covers the TfL side; **no Kafka test harness exists yet**.

`Makefile:28` `check` target = lint + test + dbt-parse + TS lint + TS
build. TM-B2 verification uses the napkin §Execution#5 gate: lint +
test + bandit (`--severity-level high`) + `make check`.

## 7. Reference patterns from prior WPs

- **TM-B1 retry policy** (`src/ingestion/tfl_client/retry.py`): bounded
  exponential backoff, hand-rolled (~30 LOC), no extra dependency.
  Honours `Retry-After` for 429/503 with positive-integer fallback to
  exponential. TM-B2 may reuse the same backoff style for Kafka
  produce errors.
- **TM-B1 tracing**: `logfire.span("tfl.request", path=..., params=...)`
  with `app_key` redacted to `***` before the span attributes are
  populated. Tested via
  `test_app_key_not_logged_via_logfire` — TM-B2's Logfire span on
  `producer.publish` should follow the same redaction discipline if
  any secret leaks into attributes (e.g. SASL credentials).
- **TM-B1 lifecycle**: async context manager owns the underlying
  `httpx.AsyncClient`; caller uses `async with TflClient(...)` and the
  client refuses requests if accessed outside the context. The
  `aiokafka.AIOKafkaProducer` documented lifecycle (`start()` /
  `stop()`) maps naturally onto an `async with` wrapper.
- **TM-B1 config minimalism**: `os.environ.get("TFL_APP_KEY", "")` +
  fail-loud constructor, no `BaseSettings` class. Same posture is
  expected for the Kafka producer config (CLAUDE.md §"Principle #1"
  rule 5).

## 8. Existing tests and harnesses

- `tests/test_contracts.py` — round-trip checks for every tier-2
  payload + event (read-only reference).
- `tests/ingestion/test_tfl_client.py` (349 LOC) — async tests using
  `httpx.MockTransport` + `monkeypatch.setattr` on
  `ingestion.tfl_client.retry.asyncio.sleep` to assert backoff
  behaviour without sleeping. Same `monkeypatch.setattr` trick should
  work for any TM-B2 producer-side `asyncio.sleep`.
- `tests/integration/` — gated by the `integration` marker
  (`pyproject.toml:62 addopts = "-m 'not integration'"`); these tests
  run only with `pytest -m integration` against the live Compose
  stack. `aiokafka` integration smoke tests (if any) belong here, not
  in the default suite.

No fixtures or helpers exist for in-memory Kafka producer testing.
TM-B2 must either:

(a) ship its own producer-side mock (e.g. an in-memory queue replacing
the `AIOKafkaProducer.send_and_wait` call site), or

(b) add an `integration` marker test that talks to the running
Redpanda container.

This is open question Q4.

## 9. Logfire wiring already in place

`src/api/observability.py` (existing) configures Logfire for the API
process. Ingestion services do not yet have an equivalent
`configure_observability` entrypoint; TM-B1's tests inject a fake
`logfire.span` via `monkeypatch`. The producer process will need its
own startup-time `logfire.configure(service_name="tfl-monitor-ingestion")`
call (CLAUDE.md §"Observability architecture — Logfire").

## 10. Out-of-track surface (read-only confirmation)

Per AGENTS.md §1, TM-B2 must NOT touch:

- `contracts/` — schemas + SQL + OpenAPI are frozen.
- `dbt/` — TM-C2's track.
- `web/` — frontend.
- `airflow/` — TM-A2.
- `src/api/`, `src/agent/` — TM-D* tracks.

Allowed surface: `src/ingestion/`, `tests/ingestion/`, plus narrow
edits to `docker-compose.yml` if a topic-creation sidecar or env wiring
is needed. The `.env.example` Kafka block already exists, so no `.env`
edits are anticipated.

## 11. Open questions for Phase 2

These need explicit author decisions before planning concludes.

1. **Q1 — Process model.** Is the producer a long-running daemon
   (`asyncio.run(loop())`) launched as its own container in
   `docker-compose.yml`, or a one-shot script invoked from Airflow on
   a 30s cadence (TM-A2 not yet landed)? The SETUP.md objective
   ("poll every 30s") fits both. A long-running daemon keeps a single
   `httpx.AsyncClient` + `AIOKafkaProducer` warm; an Airflow task
   re-instantiates each cycle. Default recommendation: long-running
   daemon, given Airflow DAGs are scheduled for TM-A2 and the
   prototype fits in one process.

2. **Q2 — Topic provisioning.** Rely on Redpanda
   `auto.create.topics.enable` (default in `--mode=dev-container`),
   or pre-create `line-status` via a one-shot `rpk topic create`
   step? Auto-creation gives 1 partition / RF=1 — fine for prototype
   but means the topic config is implicit. Pre-creation makes the
   topic config explicit and reviewable in `docker-compose.yml`.

3. **Q3 — `event_type` value.** `LineStatusEvent` does not pin an
   `event_type` literal (the `Event` base accepts any `str`). Pick a
   convention — candidates: `"line-status"` (matches topic),
   `"line-status.snapshot"` (room for future kinds),
   `"tfl.line-status.v1"` (versioned). Whatever we pick now becomes a
   stable contract once consumers (TM-B3+) start filtering on it.

4. **Q4 — Test strategy for produce path.** Three options:
   (a) ship a tiny in-memory `AIOKafkaProducer` test double (subclass
   that captures `send_and_wait` calls); (b) `monkeypatch` the
   `aiokafka.AIOKafkaProducer` symbol in the producer module and
   assert against the patched object; (c) add an `integration`
   marker test against the running Redpanda. Default recommendation:
   (b) for unit tests + (c) for one smoke test, mirroring TM-A1's
   integration-marker discipline.

5. **Q5 — Cadence implementation.** `asyncio.sleep(30)` between cycles
   vs. fixed-rate scheduling (sleep `30 - elapsed`) vs. `asyncio.create_task`
   for fire-and-forget overlapping cycles. Fixed-rate is the standard
   choice but introduces drift handling; pure 30s sleep adds drift to
   30s + cycle duration. Open: which one?

6. **Q6 — Failure isolation.** On a TfL fetch failure or Kafka produce
   failure, do we (a) abort the cycle and try again on the next tick,
   (b) retry within the cycle (reusing TM-B1's `with_retry` semantics
   for Kafka), or (c) per-event retry with a dead-letter topic? (c) is
   over-engineering for prototype; (a) loses one cycle of data on a
   transient blip; (b) is the middle ground.

7. **Q7 — Idempotency / `event_id`.** UUIDv7 is preferred per the
   `Event` envelope docstring, but Python's stdlib `uuid` module does
   not provide UUIDv7 (only v1/v3/v4/v5). Options: ship UUIDv4 with a
   docstring noting UUID7 is preferred-but-deferred; depend on a
   tiny dep like `uuid7` or `uuid-utils`; hand-roll v7 (~10 LOC,
   RFC 9562). UUIDv4 is the no-new-dep path; v7 ordering would help
   downstream sort, but Postgres `gen_random_uuid()` already defaults
   to v4 in `raw.line_status`.

8. **Q8 — Ingestion-side Logfire init.** Should TM-B2 add a tiny
   `src/ingestion/observability.py` (mirroring `src/api/observability.py`)
   that calls `logfire.configure(service_name="tfl-monitor-ingestion")`
   at startup, or inline that call in the producer entrypoint? Adding
   the helper now sets the pattern for TM-B3 / TM-B4 consumers; inline
   keeps it minimal until the second consumer arrives (CLAUDE.md
   "Principle #1" rule 4).

9. **Q9 — Compose service.** Add a new `tfl-line-status-producer`
   service to `docker-compose.yml` (build from same image, run
   `python -m ingestion.producers.line_status` or similar), or leave
   it off-Compose for TM-B2 and only land the code + `make` target
   for now? Adding it to Compose means TM-A1's `make up` brings it
   up; leaving it off keeps the WP smaller and lets TM-A5 (Railway
   deploy) wire it later.

10. **Q10 — `modes` to poll.** TM-B1's `fetch_line_statuses` takes
    `Iterable[str]`. The committed fixture covers `tube` and a
    multi-mode `tube,elizabeth-line,dlr,overground` query. SETUP.md
    objective says "line-status" without specifying modes. Default
    recommendation: `["tube", "elizabeth-line", "overground", "dlr"]`
    (the four modes the multi-mode fixture exercises), parameterised
    via env var or constant for easy expansion in TM-B4-and-beyond.

## 12. Non-goals of TM-B2 (per AGENTS.md track scope)

- No consumer (`raw.line_status` writes — TM-B3).
- No dbt staging / mart (`stg_line_status`, `mart_tube_reliability_daily`
  — TM-C2).
- No API endpoint wiring (TM-D2).
- No arrivals or disruptions topics (TM-B4).
- No Airflow DAG (TM-A2 — even if Q1 picks a long-running daemon, the
  Airflow DAG that *also* runs ingestion is a separate WP).
- No prod Redpanda / Supabase wiring (TM-A3, TM-A4).
- No edits to `contracts/` (frozen — would need an ADR).

## 13. References

- `CLAUDE.md` — §"Principle #1: lean by default"; §"Pydantic usage";
  §"Observability architecture"; §"WP scope rules".
- `AGENTS.md` — §1 "Track inventory"; §2 review checklist.
- `SETUP.md` — line 342 (TM-B2 catalogue row).
- `.claude/specs/TM-B1-plan.md` — reference for plan structure and
  retry/observability conventions.
- `.claude/napkin.md` — §Execution#5 (verification gate),
  §Domain#3 (`ingestion.foo` import style).
- `.claude/adrs/001-redpanda-over-kafka.md` — broker choice rationale.
- `contracts/schemas/line_status.py`, `contracts/schemas/common.py` —
  frozen wire format.
- `src/ingestion/tfl_client/{client,normalise}.py` — upstream surface.
- `docker-compose.yml:22-43` — Redpanda service.
- `contracts/sql/001_raw_tables.sql:12-22` — downstream `raw.line_status`.
