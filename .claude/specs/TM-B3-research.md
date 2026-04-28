# TM-B3 — Phase 1 research (read-only)

Source: GitHub issue #8 body + AGENTS.md §"Track inventory" + SETUP.md
WP-catalogue row TM-B3.
Date: 2026-04-27.
Active WP: TM-B3 — `line-status` consumer to Postgres (track
`B-ingestion`, phase 3, depends on TM-B2 ✅ and TM-A1 ✅).

This document is a **read-only audit** of the current code, contracts,
infra, and dependencies relevant to TM-B3. It does not propose an
implementation. Open questions are surfaced in §11 for Phase 2 to
resolve with the author.

## 1. Stated objective and acceptance criteria

GitHub issue #8 (`gh issue view 8`):

> Consume line-status topic and write to `raw.line_status`.

Acceptance criteria as enumerated on the issue:

1. Consumer module under `src/ingestion/consumers/line_status.py`.
2. Writes validated rows to `raw.line_status`.
3. Idempotent on retry (upsert semantics).
4. Integration test covers end-to-end producer → consumer → Postgres.
5. Logfire traces consume lag.

Implicit acceptance criteria, derived from CLAUDE.md, AGENTS.md, the
napkin, and the upstream WPs:

- Track scope: `src/ingestion/consumers/`, `tests/ingestion/`,
  optionally `docker-compose.yml` for a new consumer service. **No
  edits to `contracts/`** (frozen — would need an ADR per AGENTS.md
  §1).
- `aiokafka` is the locked Kafka client (`pyproject.toml:14`,
  ADR 001). `psycopg[binary]>=3.2` is the locked Postgres driver
  (`pyproject.toml:15`).
- Consumer must validate every message against `LineStatusEvent`
  before writing; malformed payloads must not crash the loop
  (CLAUDE.md §"Pydantic usage conventions" — Pydantic at every
  boundary; napkin §Domain#7 lesson on full-fidelity inputs).
- Failures (Kafka transient errors, Postgres transient errors,
  Pydantic validation errors) must not crash the daemon; they must be
  logged via Logfire and the next message must run (mirrors TM-B2's
  fail-soft cycle in `src/ingestion/producers/line_status.py:86-96`).
- Verification gate: `uv run task lint && uv run task test && uv run
  bandit -r src --severity-level high && make check` — all four exit
  0 (napkin §Execution#5).

## 2. Existing ingestion surface

### `src/ingestion/`

```
src/ingestion/
├── __init__.py            (empty marker)
├── Dockerfile             (TM-B2; non-root user; CMD points at producer)
├── consumers/             (empty package, reserved for TM-B3)
│   └── __init__.py
├── producers/             (TM-B2, complete)
│   ├── __init__.py        re-exports KafkaEventProducer + LineStatusProducer
│   ├── kafka.py           AIOKafkaProducer wrapper, async context manager
│   └── line_status.py     LineStatusProducer.run_forever, fail-soft
└── tfl_client/            (TM-B1, complete)
    ├── __init__.py        re-exports TflClient + 3 normalisers
    ├── client.py          async TfL HTTP client + Logfire span + redaction
    ├── normalise.py       tier-1 → tier-2 pure adapters
    └── retry.py           hand-rolled retry helper (RFC 9110 Retry-After)
```

`consumers/__init__.py` exists as an empty placeholder; no consumer
code is in flight.

### Producer surface that defines the wire contract

`src/ingestion/producers/line_status.py:101-112` is the canonical
producer that TM-B3 must consume from:

```python
event = LineStatusEvent(
    event_id=self._event_id_factory(),         # UUIDv4
    event_type=LINE_STATUS_EVENT_TYPE,         # "line-status.snapshot"
    ingested_at=self._clock(),                  # UTC datetime
    payload=payload,                            # LineStatusPayload
)
await self._kafka_producer.publish(
    LineStatusEvent.TOPIC_NAME,                 # "line-status"
    event=event,
    key=payload.line_id,                        # partition key
)
```

`KafkaEventProducer.publish` (`src/ingestion/producers/kafka.py:80-91`)
serialises the event with `event.model_dump_json().encode("utf-8")` and
sets the partition key to UTF-8 bytes. Producer-side options
(`src/ingestion/producers/kafka.py:54-60`):

```python
self._producer = self._producer_factory(
    bootstrap_servers=self._bootstrap_servers,
    client_id=self._client_id,                  # "tfl-monitor-ingestion"
    enable_idempotence=True,
    acks="all",
    linger_ms=10,
)
```

Key consequences for TM-B3:

- `event_id` is a UUIDv4 generated client-side (not a v7 ordering
  guarantee). Ordering across partitions is undefined, but TM-B2
  uses `key=payload.line_id`, so all events for a single line land
  on the same partition. Single-partition Redpanda dev cluster
  (§4) makes ordering moot for the prototype.
- `enable_idempotence=True` + `acks="all"` give producer-side
  exactly-once semantics within a single producer session. Across
  producer restarts, duplicates are still possible; the consumer
  must remain idempotent on `event_id`.
- The wire payload is JSON (UTF-8). No Avro/Protobuf — Pydantic
  `model_validate_json(bytes)` is the only deserialiser needed.

## 3. Tier-2 wire format (read by consumer)

`contracts/schemas/line_status.py` and `contracts/schemas/common.py`
define what the consumer parses. The wire payload received by TM-B3
is the JSON serialisation of a `LineStatusEvent`:

```json
{
  "event_id": "uuid-string",
  "event_type": "line-status.snapshot",
  "source": "tfl-unified-api",
  "ingested_at": "2026-04-27T10:00:00Z",
  "payload": {
    "line_id": "victoria",
    "line_name": "Victoria",
    "mode": "tube",
    "status_severity": 10,
    "status_severity_description": "Good Service",
    "reason": null,
    "valid_from": "2026-04-27T00:00:00Z",
    "valid_to": "2027-04-27T00:00:00Z"
  }
}
```

Both `LineStatusEvent` and `LineStatusPayload` are `frozen=True`. The
payload validator enforces `valid_to > valid_from` and
`0 <= status_severity <= 20`. Consumer-side parsing should use
`LineStatusEvent.model_validate_json(message.value)` to inherit all
constraints automatically; on `pydantic.ValidationError` the message
is invalid and must be logged + skipped (cannot be DLQ'd because no
DLQ topic exists in scope).

## 4. Topic / broker substrate (TM-A1 + TM-B2)

`docker-compose.yml:22-72`:

- Service `redpanda` (image `redpandadata/redpanda:v24.2.7`), single
  broker, `--mode=dev-container --smp=1`. Listeners: internal
  `redpanda:9092`, external `localhost:19092`. Healthcheck:
  `rpk cluster info`.
- Service `redpanda-init` (profile `init`) — `rpk -X
  brokers=redpanda:9092 topic create line-status --partitions 1
  --replicas 1` with idempotent error handling (treats
  `TOPIC_ALREADY_EXISTS` as success). Run via `uv run task
  init-topics` (`pyproject.toml:80`).
- Service `tfl-line-status-producer` (profile `ingest`) — TM-B2
  daemon, builds from `src/ingestion/Dockerfile`, runs `uv run
  python -m ingestion.producers.line_status`, env vars include
  `TFL_APP_KEY`, `KAFKA_BOOTSTRAP_SERVERS=redpanda:9092`,
  `LOGFIRE_TOKEN`, `ENVIRONMENT`, `APP_VERSION`.
- `redpanda-console` (profile `ui`) at `:8080` for inspection.

The `line-status` topic is **explicitly pre-created** with 1 partition
/ RF=1 by `redpanda-init` (TM-B2 round-1 review folded auto-creation
out for explicitness). TM-B3 does not need to add another `rpk topic
create` step — the topic exists once `make up && uv run task
init-topics` runs.

`.env.example:13-17` already declares the Kafka surface; SASL fields
remain placeholders for the Redpanda Cloud migration (TM-A4); local
dev runs `PLAINTEXT`.

## 5. Postgres warehouse surface (TM-A1)

`contracts/sql/001_raw_tables.sql:12-22`:

```sql
CREATE TABLE raw.line_status (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);

ALTER TABLE raw.line_status
    ALTER COLUMN event_id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN ingested_at SET DEFAULT now();
```

Column-by-column mapping from the consumed `LineStatusEvent`:

| `LineStatusEvent` field   | `raw.line_status` column | Note                                        |
|---------------------------|--------------------------|---------------------------------------------|
| `event_id` (UUID)         | `event_id` (UUID PK)     | Producer-supplied; PK enforces idempotency  |
| `ingested_at` (datetime)  | `ingested_at` (TSTZ)     | Producer-supplied; DB default is fallback   |
| `event_type` (str)        | `event_type` (TEXT)      | "line-status.snapshot"                      |
| `source` (Literal)        | `source` (TEXT)          | "tfl-unified-api"                           |
| `payload` (model)         | `payload` (JSONB)        | `payload.model_dump_json()` → JSONB cast    |

Idempotency story: `event_id UUID PRIMARY KEY` rejects duplicates on
insert. Two upsert idioms apply:

(a) `INSERT … ON CONFLICT (event_id) DO NOTHING` — no-op on
duplicates, no extra round trip, returns `rowcount=0` for skipped
rows so the consumer can log dedup metrics.

(b) `INSERT … ON CONFLICT (event_id) DO UPDATE SET …` — overwrites
on duplicate; pointless for an immutable envelope.

(a) is the right choice: events are append-only and `event_id` is
content-stable from the producer, so a duplicate carries identical
data.

Postgres dev credentials live in `.env.example:5-9` (`POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB` and the host-mapped port 5432). The
consumer needs a `DATABASE_URL` or equivalent
`postgresql://user:pass@host:port/db` connection string.

`tests/integration/test_sql_init.py:36-39` shows the existing pattern
for opening a sync `psycopg.connect(DATABASE_URL)` — the integration
suite is gated on `DATABASE_URL` being set.

## 6. aiokafka consumer surface (library reference)

`pyproject.toml:14` already locks `aiokafka>=0.12`. The library
provides `AIOKafkaConsumer`, lifecycle managed via `await
consumer.start()` / `await consumer.stop()` (parallels the producer
side). Typical signature relevant to TM-B3:

```python
from aiokafka import AIOKafkaConsumer

consumer = AIOKafkaConsumer(
    "line-status",
    bootstrap_servers="redpanda:9092",
    group_id="tfl-line-status-consumer",
    enable_auto_commit=False,        # commit after DB insert
    auto_offset_reset="earliest",    # or "latest"
    client_id="tfl-monitor-ingestion-line-status-consumer",
)
await consumer.start()
try:
    async for msg in consumer:
        # parse + insert + commit
        ...
finally:
    await consumer.stop()
```

Open questions about consumer-group naming, offset reset policy,
auto-commit vs manual commit, and lag-tracing approach are surfaced
in §11.

The mypy override at `pyproject.toml:59-61` already covers
`aiokafka.*` — no new mypy ignores needed.

## 7. Postgres async-driver surface

`pyproject.toml:15` locks `psycopg[binary]>=3.2`. `psycopg` v3 ships
both sync and async APIs:

- `psycopg.AsyncConnection.connect(conninfo)` — async connect.
- `await conn.execute(query, params)` — parameterised execution
  (parameter binding is a hard rule per CLAUDE.md §"Security-first
  engineering" — no string concatenation).
- `psycopg.AsyncConnectionPool` from `psycopg_pool` — pool helper,
  but `psycopg_pool` is NOT in `pyproject.toml`, so introducing a
  pool would require a justified dep add (AGENTS.md §6).

Single-daemon process with one connection is the lean choice. JSONB
binding: pass a JSON-encoded string and cast with `%s::jsonb`, or
register `psycopg.types.json.Jsonb(payload_dict)` as a parameter — the
latter avoids round-tripping the bytes through Python text.

`src/api/observability.py:29` already calls
`logfire.instrument_psycopg("psycopg")`; the consumer's
`logfire.configure(...)` startup must call the same instrumentation
for query timings to show up in Logfire. This sets up the open
question of a shared `src/ingestion/observability.py` (Q12).

## 8. Reference patterns from prior WPs (must mirror)

- **TM-B2 lifecycle** (`src/ingestion/producers/line_status.py:138-156`):
  `_amain()` configures Logfire, validates env, opens an `async with
  TflClient(...) as ..., KafkaEventProducer(...) as ...:` block, then
  enters `run_forever`. TM-B3 will mirror with `async with
  AsyncConnection.connect(...) as ..., AIOKafkaConsumer wrapper as
  ...:` lifecycle.
- **TM-B2 fail-soft loop**
  (`src/ingestion/producers/line_status.py:86-121`):
  `try/except TflClientError → logfire.warn + return 0`,
  `try/except Exception → logfire.error + return 0` for the unknown
  catch-all (with `# noqa: BLE001 - safety net keeps daemon alive`).
  TM-B3's per-message catch should follow the same shape:
  `pydantic.ValidationError → warn + skip`,
  `psycopg.OperationalError → warn + skip + DO NOT commit`,
  `Exception → error + skip + DO NOT commit`.
- **TM-B2 Logfire span**
  (`src/ingestion/producers/kafka.py:97-106`):
  `with logfire.span("kafka.publish", topic=..., key=...,
  event_type=...): ...`. TM-B3 should emit symmetric
  `kafka.consume` and `db.insert` spans.
- **TM-B2 minimal config posture**
  (`src/ingestion/producers/line_status.py:138-149`):
  `os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")` + fail-loud
  `SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")`. CLAUDE.md
  §"Principle #1" rule 5 — no `BaseSettings` until ≥15 vars.
- **Import style** (napkin §Domain#3): `from ingestion.consumers.line_status
  import ...`, never `from src.ingestion...`.
- **TM-B2 unit test fake** (`tests/ingestion/test_kafka_producer.py:22-46`):
  `_FakeAIOKafkaProducer` records calls; `producer_factory`
  parameter on the wrapper lets tests inject the fake without
  `monkeypatch`. TM-B3 should ship the symmetric
  `_FakeAIOKafkaConsumer` test double.

## 9. Logfire wiring already in place

`src/api/observability.py` configures Logfire for the API process.
TM-B2's producer entrypoint
(`src/ingestion/producers/line_status.py:139-145`) inlines the same
configure call rather than extracting a helper. CLAUDE.md
§"Principle #1" rule 4 ("no abstractions until the second consumer
arrives") is now ambiguous: TM-B3 is the second ingestion service,
which is the trigger condition for extracting a tiny
`src/ingestion/observability.py`. See Q12.

Whichever path is picked, the consumer process must call:

```python
logfire.configure(
    service_name="tfl-monitor-ingestion",   # same as producer
    service_version=os.getenv("APP_VERSION", "0.0.1"),
    environment=os.getenv("ENVIRONMENT", "local"),
    send_to_logfire="if-token-present",
)
logfire.instrument_psycopg("psycopg")       # for DB query spans
```

`logfire.instrument_httpx()` is producer-only (no httpx in the
consumer path).

## 10. Existing tests and harnesses

- `tests/ingestion/conftest.py:1-71` — TfL fixtures only. No Kafka
  or Postgres helpers.
- `tests/ingestion/test_kafka_producer.py:22-46` —
  `_FakeAIOKafkaProducer` pattern; symmetric `_FakeAIOKafkaConsumer`
  is the obvious unit-test substrate for the consumer.
- `tests/ingestion/test_line_status_producer.py` (existing) — tests
  `run_once` with stub TfL + fake Kafka, asserts `published`
  counter, asserts Logfire metrics shape. Same shape applies to a
  consumer `run_once` (process N messages and commit).
- `tests/ingestion/integration/test_redpanda_smoke.py` — gated
  `pytest -m integration`, opens `KafkaEventProducer` against live
  Redpanda. Adds the precedent for a TM-B3
  `tests/ingestion/integration/test_consumer_smoke.py` that gates
  on **both** `KAFKA_BOOTSTRAP_SERVERS` and `DATABASE_URL`.
- `tests/integration/test_sql_init.py:36-39` — sync
  `psycopg.connect(DATABASE_URL)` pattern; gated on `DATABASE_URL`.
- `pyproject.toml:67` — default test run filters out `integration`
  via `addopts = "-m 'not integration'"`. TM-B3 must keep the
  default suite hermetic.

Gap: no Postgres test harness exists. The consumer's unit tests
need either a `_FakeAsyncConnection` (records `execute` calls), or
they need to mock `psycopg.AsyncConnection.connect`. Following the
`producer_factory` precedent, a `connection_factory` constructor
parameter on the consumer wrapper is the cleanest unit-test seam.

## 11. Open questions for Phase 2

These need explicit author decisions before planning concludes.

1. **Q1 — Process model.** Long-running `asyncio.run(loop())` daemon
   under a new Compose service (mirror of TM-B2's
   `tfl-line-status-producer`), or a one-shot consume-batch script
   suitable for Airflow scheduling (TM-A2)? Default recommendation:
   long-running daemon, mirroring TM-B2 and the AC bullet "Logfire
   traces consume lag" (lag is meaningful only for a continuous
   consumer).

2. **Q2 — Consumer group_id naming.** Candidates: `"tfl-monitor-line-status"`,
   `"tfl-monitor-line-status-v1"` (versioned, future-proof for
   format breaks), `"raw-line-status-writer"` (role-named). The
   group_id is a stable contract — once consumers commit offsets,
   renaming forces a re-read from `auto_offset_reset`. Default
   recommendation: `"tfl-monitor-line-status-writer"` (role +
   service prefix).

3. **Q3 — `auto_offset_reset` policy.** `"earliest"` reads from the
   start on a fresh group (replays the topic on first deploy);
   `"latest"` skips backlog (loses pre-deploy events). Default
   recommendation: `"earliest"` — the topic is short-lived (30s
   poll cadence) and replays are bounded; idempotency on
   `event_id` makes replays safe.

4. **Q4 — Commit strategy.** `enable_auto_commit=True` (default 5s
   interval) risks committing before DB write succeeds, which would
   lose events on a daemon restart. `enable_auto_commit=False` +
   `await consumer.commit()` after a successful insert gives
   at-least-once + idempotent. Default recommendation: manual
   commit after DB insert succeeds.

5. **Q5 — Idempotency idiom.** `INSERT … ON CONFLICT (event_id) DO
   NOTHING` (one round trip, no exception) vs `try INSERT / except
   UniqueViolation` (catches the dup as a side effect). Default
   recommendation: `ON CONFLICT DO NOTHING` — no exception
   gymnastics, log the `rowcount=0` skip in the same Logfire span.

6. **Q6 — Postgres connection lifecycle.** Single async connection
   for the daemon's lifetime (reconnect on `OperationalError`), or
   `psycopg_pool.AsyncConnectionPool` (new dependency). Default
   recommendation: single connection — it satisfies the lean
   default and a 30s/event cadence does not warrant pooling.

7. **Q7 — Lag-tracing implementation.** `consumer.position(tp)` vs
   `consumer.committed(tp)` vs computing
   `latest_offset - committed_offset` per partition. Logfire
   accepts arbitrary span attributes; a `kafka.consume` span with
   `partition`, `offset`, `lag` attributes is the simplest approach.
   Cadence: per-message (cheap, per-span) or every N messages (less
   noise). Default recommendation: per-message attribute on the
   existing `kafka.consume` span; `lag = end_offset - msg.offset` at
   batch boundaries (every N messages or every M seconds), since
   `end_offsets` is an extra round trip.

8. **Q8 — `event_type` filtering.** The producer pins
   `event_type="line-status.snapshot"`. Should the consumer
   defensively skip messages with an unknown `event_type` (logs
   `event_type` as a span attribute and increments a skip counter),
   or trust the topic name and consume everything that
   `LineStatusEvent.model_validate_json` accepts? Default
   recommendation: trust the topic + Pydantic validation; skip
   only on `pydantic.ValidationError`.

9. **Q9 — Integration smoke test layout.** Gate on `pytest -m
   integration` plus both `KAFKA_BOOTSTRAP_SERVERS` and
   `DATABASE_URL` env vars (mirroring the pattern in
   `tests/integration/test_sql_init.py:22-30`). The smoke test
   produces one event via `KafkaEventProducer`, runs the consumer's
   `run_once` (or batch-of-1 helper), and asserts a row in
   `raw.line_status`. Default recommendation: yes — `tests/ingestion/
   integration/test_consumer_smoke.py`.

10. **Q10 — Compose service for the consumer.** Add
    `tfl-line-status-consumer` to `docker-compose.yml` (build from
    same `src/ingestion/Dockerfile`, run `python -m
    ingestion.consumers.line_status`, add `DATABASE_URL` env var),
    or leave it off-Compose for TM-B3 and only land the code +
    `taskipy` task for now? Adding it to Compose mirrors the
    producer service and lets `docker compose --profile ingest up`
    start the full ingest path. Default recommendation: add the
    service.

11. **Q11 — Failure isolation per message.** On
    `pydantic.ValidationError` for a single message: skip + commit
    (poison-pill safe but loses bad data) vs skip + do NOT commit
    (replays the bad message forever). Default recommendation: skip
    + commit + Logfire `warn` with the raw bytes truncated to
    256 chars; a poison pill should not block the partition.
    Discussion needed: is a malformed message "data we never want to
    see" (drop it) or "data we should re-investigate" (DLQ)? DLQ
    is out of scope for TM-B3 (no DLQ topic provisioned).

12. **Q12 — Observability helper extraction.** Two ingestion services
    now exist (TM-B2 producer + TM-B3 consumer). Extract
    `src/ingestion/observability.py` with a tiny `configure_logfire()`
    helper, and update the producer to use it (one-line change), or
    duplicate the 5-line `logfire.configure(...)` call in the
    consumer entrypoint? CLAUDE.md §"Principle #1" rule 4 favours
    extraction once two consumers exist; but the call site is short
    enough that duplication is also defensible. Default
    recommendation: extract the helper now (consistent service_name
    is the genuine win, not LOC).

13. **Q13 — `taskipy` task entry.** Add
    `consume-line-status = "python -m ingestion.consumers.line_status"`
    next to `ingest-line-status` in `[tool.taskipy.tasks]` for
    parity. Default recommendation: yes.

14. **Q14 — Default poll/timeout values.**
    `AIOKafkaConsumer.getmany(timeout_ms=...)` vs `async for msg in
    consumer`. The async-iterator form blocks indefinitely waiting
    for the next message; the consumer's main loop already lives
    inside `async for`, so there is no idle-loop problem. Default
    recommendation: `async for msg in consumer:` — simplest and
    matches aiokafka idiomatic usage.

## 12. Non-goals of TM-B3 (per AGENTS.md track scope)

- No new dbt staging / mart (`stg_line_status`,
  `mart_tube_reliability_daily` — TM-C2).
- No API endpoint wiring (`/status/live` etc. — TM-D2).
- No arrivals or disruptions consumers (TM-B4).
- No Airflow DAG (TM-A2).
- No prod Supabase / Redpanda Cloud wiring (TM-A3, TM-A4).
- No edits to `contracts/` (frozen).
- No DLQ topic, no schema-registry, no Avro/Protobuf migration.
- No `psycopg_pool` dependency unless a real concurrency requirement
  surfaces.
- No custom metrics/tracing beyond Logfire spans (CLAUDE.md
  §"Anti-patterns to avoid").

## 13. References

- `CLAUDE.md` — §"Principle #1: lean by default"; §"Pydantic usage
  conventions"; §"Observability architecture"; §"Security-first
  engineering"; §"WP scope rules".
- `AGENTS.md` — §1 "PR rules: WP scope"; §6 "Dependencies" (new dep
  needs justification).
- GitHub issue #8 — TM-B3 stated AC.
- `.claude/specs/TM-B2-research.md`, `.claude/specs/TM-B2-plan.md` —
  reference structure and producer-side decisions.
- `.claude/napkin.md` — §Execution#5 (verification gate); §Domain#3
  (`ingestion.foo` import style).
- `.claude/adrs/001-redpanda-over-kafka.md` — broker choice rationale.
- `contracts/schemas/line_status.py`, `contracts/schemas/common.py` —
  frozen wire format.
- `contracts/sql/001_raw_tables.sql:12-22` — `raw.line_status` DDL.
- `src/ingestion/producers/{kafka,line_status}.py` — producer surface
  defining the wire format and lifecycle pattern to mirror.
- `src/api/observability.py` — `logfire.configure` + `instrument_psycopg`
  pattern.
- `tests/ingestion/test_kafka_producer.py:22-46` — `_FakeAIOKafkaProducer`
  pattern for the symmetric consumer fake.
- `tests/integration/test_sql_init.py:22-39` — `DATABASE_URL`-gated
  integration test pattern.
- `docker-compose.yml:22-89` — Redpanda + topic init + producer
  service substrate.
