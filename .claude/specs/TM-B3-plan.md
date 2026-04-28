# TM-B3 — Implementation plan (Phase 2)

Source: `TM-B3-research.md` + author decisions on `2026-04-27`.

All fourteen open questions resolved as the recommended defaults from
the research file, plus the four extension points decided in chat:

- **Q1 — Process model:** long-running async daemon
  (`asyncio.run(run_forever())`), mirrors TM-B2's
  `LineStatusProducer.run_forever`.
- **Q2 — Consumer `group_id`:** `"tfl-monitor-line-status-writer"`.
- **Q3 — `auto_offset_reset`:** `"earliest"` — first deploy replays the
  topic; idempotency on `event_id` makes replays safe.
- **Q4 — Commit strategy:** `enable_auto_commit=False` + `await
  consumer.commit()` after a successful DB insert; at-least-once with
  PK-based dedup.
- **Q5 — Idempotency idiom:** `INSERT … ON CONFLICT (event_id) DO
  NOTHING`; log `rowcount` on the `db.insert` Logfire span.
- **Q6 — Postgres connection lifecycle:** single `psycopg.AsyncConnection`
  for the daemon's lifetime, reconnect on `psycopg.OperationalError`.
  No `psycopg_pool` dependency.
- **Q7 — Lag-tracing implementation:** per-message `kafka.consume` span
  with `partition` and `offset` attributes; `lag` (= `end_offset -
  msg.offset`) refreshed every **50 messages OR every 30 s**, whichever
  comes first, via a single `await consumer.end_offsets(...)` round
  trip; cached lag attached to spans between refreshes.
- **Q8 — `event_type` filtering:** trust topic + Pydantic; only
  `pydantic.ValidationError` triggers a skip.
- **Q9 — Integration smoke layout:** new
  `tests/ingestion/integration/test_consumer_smoke.py`, gated on both
  `KAFKA_BOOTSTRAP_SERVERS` and `DATABASE_URL`.
- **Q10 — Compose service:** add `tfl-line-status-consumer` to
  `docker-compose.yml`, profile `ingest`, builds from existing
  `src/ingestion/Dockerfile`.
- **Q11 — Failure isolation per message:** poison pill = skip + commit
  + Logfire `warn` with raw bytes truncated to 256 chars. No DLQ
  (out of scope).
- **Q12 — Observability helper extraction:** introduce
  `src/ingestion/observability.py` with a `configure_logfire()` helper;
  migrate the producer's inline `logfire.configure(...)` to it (one-line
  diff). TM-B3 is the second ingestion service — the trigger condition
  in CLAUDE.md "Principle #1" rule 4.
- **Q13 — `taskipy` task:** add
  `consume-line-status = "python -m ingestion.consumers.line_status"`
  next to `ingest-line-status`.
- **Q14 — Poll loop:** `async for msg in consumer:` (idiomatic aiokafka).

Extension points decided in chat:

- **Lag refresh cadence:** N=50 messages OR M=30 s, whichever fires
  first.
- **Batch size:** 1 message → 1 insert → 1 commit. The 30 s producer
  cadence × handful of lines = trivial throughput; micro-batching is
  YAGNI.
- **`isolation_level`:** aiokafka default `read_uncommitted` — producer
  does not use Kafka transactions.
- **Postgres reconnect:** on `OperationalError`, close the connection,
  `await asyncio.sleep(1.0)`, reopen, and **do NOT commit the offset**
  for the in-flight message (replay on the next iteration).

## Summary

Land the `line-status` Kafka → Postgres consumer under
`src/ingestion/consumers/line_status.py`, plus a thin async wrapper
around `AIOKafkaConsumer` under `src/ingestion/consumers/kafka.py`,
plus a tiny `src/ingestion/observability.py` helper shared with the
producer, plus a `tfl-line-status-consumer` Compose service. The
consumer subscribes to topic `"line-status"`, validates every message
against `LineStatusEvent`, inserts the validated envelope into
`raw.line_status` via `INSERT … ON CONFLICT (event_id) DO NOTHING`,
and commits the Kafka offset only after the insert succeeds. Failures
(Pydantic, Postgres transient, unknown) are logged via Logfire and the
loop continues. Lag is reported on every `kafka.consume` span with a
30 s / 50 msg refresh cadence. No edits to `contracts/`. No producer
changes beyond a one-line swap to the new Logfire helper.

## Execution mode

- **Author of change:** single-track WP — execute serially in the main
  workspace (only `src/ingestion/` + tests + Compose touched; no
  contracts edits, no concurrent track).
- **Branch:** `feature/TM-B3-line-status-consumer`.
- **PR title:** `feat(ingestion): TM-B3 line-status consumer to Postgres (TM-8)`.
- **PR body:** `Closes TM-8`; lists deliverables, the commit-after-insert
  semantics, the idempotency idiom, the Compose service, and the
  observability-helper extraction footnote.

## What we're NOT doing

- No producer changes other than the one-line migration to
  `configure_logfire()` (Q12).
- No edits to `contracts/schemas/*` or `contracts/sql/*` — frozen.
- No DLQ topic; poison pills are skip-and-commit (Q11).
- No `psycopg_pool` dependency — single connection is sufficient (Q6).
- No `Settings(BaseSettings)` class — three env vars
  (`KAFKA_BOOTSTRAP_SERVERS`, `DATABASE_URL`, optional `LOGFIRE_TOKEN`);
  CLAUDE.md "Principle #1" rule 5 forbids it.
- No new runtime dependency. `aiokafka>=0.12`, `psycopg[binary]>=3.2`,
  `pydantic`, `logfire` are already in `pyproject.toml`.
- No arrivals or disruptions consumers — TM-B4.
- No Airflow DAG — TM-A2.
- No prod Supabase / Redpanda Cloud wiring — TM-A3, TM-A4.
- No dbt staging / mart on top of `raw.line_status` — TM-C2.
- No `/status/live` endpoint wiring — TM-D2.
- No custom metrics/tracing — Logfire spans cover what we need
  (CLAUDE.md "Anti-patterns to avoid").

## Sub-phases

### Phase 3.1 — Observability helper extraction (Q12)

#### `src/ingestion/observability.py` (new)

```python
"""Shared Logfire setup for ingestion services."""

from __future__ import annotations

import os

import logfire

INGESTION_SERVICE_NAME = "tfl-monitor-ingestion"


def configure_logfire(*, instrument_psycopg: bool = False) -> None:
    """Configure Logfire for an ingestion service entrypoint.

    Args:
        instrument_psycopg: When ``True`` also enables psycopg span
            instrumentation (consumer-only; producer does not open a
            DB connection).
    """
    logfire.configure(
        service_name=INGESTION_SERVICE_NAME,
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    if instrument_psycopg:
        logfire.instrument_psycopg("psycopg")
```

#### `src/ingestion/producers/line_status.py` (one-line migration)

Replace the inline `logfire.configure(...)` block in `_amain` with
`configure_logfire()` (no `instrument_psycopg`). Keep
`logfire.instrument_httpx()` adjacent — it stays producer-only.

`src/api/observability.py` is **out of scope** — it has its own
`logfire.instrument_fastapi(app)` step and a different service name.
Do not touch it.

### Phase 3.2 — Consumer wrapper module

#### `src/ingestion/consumers/__init__.py`

Re-export the public surface used by tests + the entrypoint:

```python
"""Kafka → Postgres consumers for TfL ingestion."""

from ingestion.consumers.kafka import KafkaEventConsumer, KafkaConsumerError
from ingestion.consumers.line_status import (
    LINE_STATUS_CONSUMER_GROUP_ID,
    LINE_STATUS_LAG_REFRESH_MESSAGES,
    LINE_STATUS_LAG_REFRESH_SECONDS,
    LineStatusConsumer,
)

__all__ = [
    "KafkaConsumerError",
    "KafkaEventConsumer",
    "LINE_STATUS_CONSUMER_GROUP_ID",
    "LINE_STATUS_LAG_REFRESH_MESSAGES",
    "LINE_STATUS_LAG_REFRESH_SECONDS",
    "LineStatusConsumer",
]
```

#### `src/ingestion/consumers/kafka.py` (new)

Thin async wrapper around `aiokafka.AIOKafkaConsumer`, mirror of
TM-B2's `KafkaEventProducer`. Single consumer of this abstraction =
aligns with CLAUDE.md "Principle #1" rule 4 (no premature factory).

Public surface:

```python
class KafkaConsumerError(RuntimeError):
    """Raised when the underlying consumer cannot start, commit, or fetch offsets."""


class KafkaEventConsumer:
    """Async JSON Kafka consumer wrapping ``AIOKafkaConsumer``."""

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str,
        *,
        group_id: str,
        client_id: str = "tfl-monitor-ingestion-line-status-consumer",
        auto_offset_reset: str = "earliest",
        consumer_factory: Callable[..., AIOKafkaConsumer] | None = None,
    ) -> None: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...

    def __aiter__(self) -> AsyncIterator[ConsumerRecord]: ...

    async def commit(self) -> None: ...

    async def end_offsets(
        self, partitions: Iterable[TopicPartition]
    ) -> dict[TopicPartition, int]: ...
```

Implementation details:

- Constructor stores config; defers `AIOKafkaConsumer` instantiation
  to `__aenter__` so a `consumer_factory` test double can replace the
  underlying client without touching `aiokafka` imports (mirrors
  `producer_factory` precedent in `KafkaEventProducer`).
- `__aenter__` builds the underlying consumer with
  `enable_auto_commit=False`, `auto_offset_reset=self._auto_offset_reset`,
  `group_id=self._group_id`, `client_id=self._client_id`, and the
  positional topic argument; calls `await consumer.start()`.
- `__aexit__` calls `await consumer.stop()`.
- `__aiter__` yields directly from the underlying consumer
  (`return self._consumer.__aiter__()`).
- `commit` / `end_offsets` delegate to the underlying consumer; both
  wrap `aiokafka.errors.KafkaError` into `KafkaConsumerError`.
- All public methods (start, stop, commit, end_offsets) emit Logfire
  spans named `kafka.consumer.<op>` for visibility.

### Phase 3.3 — Postgres writer module

#### `src/ingestion/consumers/postgres.py` (new)

Tiny helper module so the consumer module stays focused on the
business loop. Three responsibilities only.

```python
"""Postgres writer for ``raw.line_status``."""

from __future__ import annotations

from typing import Self

import logfire
import psycopg
from psycopg.types.json import Jsonb

from contracts.schemas.line_status import LineStatusEvent

INSERT_RAW_LINE_STATUS_SQL = """
INSERT INTO raw.line_status (event_id, ingested_at, event_type, source, payload)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (event_id) DO NOTHING
"""


class RawLineStatusWriter:
    """Owns a single async psycopg connection; reconnects on transient errors."""

    def __init__(self, dsn: str) -> None: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def insert(self, event: LineStatusEvent) -> int:
        """Insert one envelope; returns ``rowcount`` (1 = inserted, 0 = duplicate)."""

    async def reconnect(self) -> None:
        """Close + reopen the connection. Used after ``OperationalError``."""
```

Implementation details:

- `__aenter__` opens with `psycopg.AsyncConnection.connect(dsn,
  autocommit=True)`. `autocommit=True` so each insert commits
  independently without an explicit transaction wrapper — duplicates
  are handled at the SQL level via `ON CONFLICT`.
- `insert` encodes the payload as `Jsonb(event.payload.model_dump(mode="json"))`
  and binds positional parameters: `(event.event_id, event.ingested_at,
  event.event_type, event.source, Jsonb(...))`. Wraps the call in
  `logfire.span("db.insert", table="raw.line_status",
  event_id=str(event.event_id))` and attaches `rowcount` to the span
  before returning.
- `reconnect` swallows close errors, sleeps 1 s
  (`await asyncio.sleep(1.0)`), and reopens. On second-level failure
  the surrounding loop catches and continues — the daemon never
  crashes mid-reconnect.

`Jsonb` from `psycopg.types.json` is the documented v3 path; no
`%s::jsonb` cast needed (CLAUDE.md §"Security-first": parameterised
queries always).

### Phase 3.4 — `src/ingestion/consumers/line_status.py`

Constants:

```python
LINE_STATUS_CONSUMER_GROUP_ID = "tfl-monitor-line-status-writer"
LINE_STATUS_LAG_REFRESH_MESSAGES = 50
LINE_STATUS_LAG_REFRESH_SECONDS = 30.0
_POISON_PILL_PREVIEW_BYTES = 256
```

Class:

```python
class LineStatusConsumer:
    """Consumes ``line-status`` and writes ``raw.line_status`` rows."""

    def __init__(
        self,
        *,
        kafka_consumer: KafkaEventConsumer,
        writer: RawLineStatusWriter,
        clock: Callable[[], float] = time.monotonic,
        lag_refresh_messages: int = LINE_STATUS_LAG_REFRESH_MESSAGES,
        lag_refresh_seconds: float = LINE_STATUS_LAG_REFRESH_SECONDS,
    ) -> None: ...

    async def run_once(self, max_messages: int | None = None) -> int:
        """Consume up to ``max_messages`` messages then return.

        Returns the number of messages successfully inserted (excludes
        duplicates and skipped poison pills). Used by tests; the
        production loop calls ``run_forever``.
        """

    async def run_forever(self) -> NoReturn:
        """Run the consume → validate → insert → commit loop forever."""
```

Per-message flow (sketch):

```python
async def _process_one(self, msg: ConsumerRecord) -> bool:
    with logfire.span(
        "kafka.consume",
        topic=msg.topic,
        partition=msg.partition,
        offset=msg.offset,
        lag=self._cached_lag.get(msg.partition),
    ):
        try:
            event = LineStatusEvent.model_validate_json(msg.value)
        except pydantic.ValidationError as exc:
            logfire.warn(
                "ingestion.line_status.poison_pill",
                error=repr(exc),
                preview=_truncate(msg.value, _POISON_PILL_PREVIEW_BYTES),
            )
            await self._kafka_consumer.commit()      # skip + commit
            return False

        try:
            inserted = await self._writer.insert(event)
        except psycopg.OperationalError as exc:
            logfire.warn(
                "ingestion.line_status.db_transient",
                error=repr(exc),
                event_id=str(event.event_id),
            )
            await self._writer.reconnect()
            return False                             # do NOT commit; replay
        except Exception as exc:                     # noqa: BLE001 - safety net
            logfire.error(
                "ingestion.line_status.unknown_failure",
                error=repr(exc),
                event_id=str(event.event_id),
            )
            return False                             # do NOT commit; replay

        await self._kafka_consumer.commit()
        return bool(inserted)
```

`run_forever` (lag-aware loop):

```python
async def run_forever(self) -> NoReturn:
    last_refresh = self._clock()
    seen_since_refresh = 0
    async for msg in self._kafka_consumer:
        await self._process_one(msg)
        seen_since_refresh += 1
        elapsed = self._clock() - last_refresh
        if (
            seen_since_refresh >= self._lag_refresh_messages
            or elapsed >= self._lag_refresh_seconds
        ):
            await self._refresh_lag()
            seen_since_refresh = 0
            last_refresh = self._clock()
```

`_refresh_lag` calls `await self._kafka_consumer.end_offsets(...)` for
every assigned partition and updates `self._cached_lag[partition] =
end_offset - last_seen_offset`. On `KafkaConsumerError` it logs a
`logfire.warn` and leaves the cache untouched — lag tracing is
best-effort, never blocks the main loop.

Module-level entrypoint:

```python
async def _amain() -> None:
    configure_logfire(instrument_psycopg=True)

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    async with (
        KafkaEventConsumer(
            LineStatusEvent.TOPIC_NAME,
            bootstrap_servers=bootstrap,
            group_id=LINE_STATUS_CONSUMER_GROUP_ID,
        ) as kafka,
        RawLineStatusWriter(dsn) as writer,
    ):
        consumer = LineStatusConsumer(kafka_consumer=kafka, writer=writer)
        await consumer.run_forever()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
```

Notes:

- Both env-var checks are fail-loud (CLAUDE.md §"Security-first": never
  default-empty for boundary configs).
- `instrument_psycopg=True` so DB query timings show up in Logfire
  spans (research §7).
- `clock` injection point exists purely for deterministic unit tests;
  default `time.monotonic` matches TM-B2's `run_forever` precedent.

### Phase 3.5 — Compose service + taskipy + Makefile

`docker-compose.yml` — append after `tfl-line-status-producer`:

```yaml
  tfl-line-status-consumer:
    build:
      context: .
      dockerfile: src/ingestion/Dockerfile
    profiles: ["ingest"]
    restart: unless-stopped
    depends_on:
      redpanda:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
      DATABASE_URL: postgresql://${POSTGRES_USER:-tflmonitor}:${POSTGRES_PASSWORD:-change_me}@postgres:5432/${POSTGRES_DB:-tflmonitor}
      LOGFIRE_TOKEN: ${LOGFIRE_TOKEN:-}
      ENVIRONMENT: ${ENVIRONMENT:-local}
      APP_VERSION: ${APP_VERSION:-0.0.1}
    command: ["uv", "run", "python", "-m", "ingestion.consumers.line_status"]
```

Notes:

- Reuses `src/ingestion/Dockerfile` from TM-B2 — no new image build
  surface.
- `profiles: ["ingest"]` matches the producer service so
  `docker compose --profile ingest up` starts the full pipeline.
- `depends_on: postgres: condition: service_healthy` enforces ordering
  on `make up`; the existing healthcheck in the postgres service is
  already in place (`pg_isready`).
- The `DATABASE_URL` substitution uses Compose-side defaults that match
  `.env.example`. No new placeholder is needed in `.env.example`
  (DATABASE_URL is **not** added there for the producer track since the
  consumer is the only ingestion service that needs it; if the author
  prefers parity, a follow-up `.env.example` line is a 1-line change).

`pyproject.toml` `[tool.taskipy.tasks]` — add next to
`ingest-line-status`:

```
consume-line-status = "python -m ingestion.consumers.line_status"
```

`Makefile` — add a target next to `ingest-line-status`:

```
consume-line-status: ## Run line-status consumer locally (host-side, against Compose Redpanda + Postgres)
	uv run python -m ingestion.consumers.line_status
```

Total Makefile target count after this WP: 10 — well under the 15-target
ceiling in CLAUDE.md "Principle #1" rule 2.

### Phase 3.6 — Tests

#### `tests/ingestion/conftest.py`

Add two test doubles + helpers, beside the existing TfL fixtures.

```python
class _FakeAIOKafkaConsumer:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.started = False
        self.stopped = False
        self.committed: int = 0
        self._records: list[ConsumerRecord] = []
        self._end_offsets: dict[TopicPartition, int] = {}

    def queue(self, record: ConsumerRecord) -> None: ...
    def set_end_offsets(self, mapping: dict[TopicPartition, int]) -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def commit(self) -> None: ...
    async def end_offsets(self, _: Iterable[TopicPartition]) -> dict[TopicPartition, int]: ...

    def __aiter__(self) -> AsyncIterator[ConsumerRecord]: ...


class _FakeAsyncConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_next: Exception | None = None
        self.closed = False

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor: ...
    async def close(self) -> None: ...
```

#### `tests/ingestion/test_line_status_consumer.py`

Unit tests using the fakes + a deterministic clock:

1. `test_run_once_inserts_one_row_per_event` — queue 3 valid
   `LineStatusEvent` records, assert 3 `INSERT` calls bound with
   matching `event_id` / `ingested_at` / `event_type` / `source` /
   `payload`, and 3 `commit()` calls on the fake consumer.
2. `test_run_once_skips_and_commits_poison_pill` — queue one record
   whose `value` is `b"{not json"`; assert no DB call, **one**
   `commit()` call, and a Logfire warn with a 256-byte preview.
3. `test_run_once_does_not_commit_on_db_operational_error` — fake
   connection raises `OperationalError` on first `execute`; assert no
   `commit()`, and that `_writer.reconnect()` was invoked exactly once.
4. `test_run_once_does_not_commit_on_unknown_db_error` — fake raises
   `RuntimeError`; assert no `commit()` and no reconnect.
5. `test_duplicate_returns_zero_rowcount_but_still_commits` —
   mock `INSERT … ON CONFLICT DO NOTHING` returning `rowcount=0`;
   assert `commit()` was still called (the message *was* processed).
6. `test_run_forever_refreshes_lag_after_n_messages` — queue 60 valid
   records, run loop until exhausted via a `StopIteration`-style
   sentinel; assert `end_offsets` was called once at the 50-message
   boundary and the cached `lag` attribute appears on the
   `kafka.consume` span for messages 51..60.
7. `test_run_forever_refreshes_lag_after_period` — queue 5 records
   with an injected clock that advances 31 s between messages 3 and 4;
   assert `end_offsets` was called once between messages 3 and 4.

#### `tests/ingestion/test_kafka_consumer.py`

Unit tests for the `KafkaEventConsumer` wrapper, mirror of
`test_kafka_producer.py`:

1. `test_aenter_starts_and_aexit_stops_consumer`.
2. `test_aiter_delegates_to_underlying_consumer` — yield three records
   from the fake; assert all three flow through the wrapper.
3. `test_commit_translates_kafka_error_to_kafka_consumer_error`.
4. `test_end_offsets_translates_kafka_error_to_kafka_consumer_error`.
5. `test_constructor_passes_group_id_and_auto_offset_reset_to_factory` —
   assert `consumer_factory` was called with `group_id`,
   `auto_offset_reset`, `enable_auto_commit=False`, and the topic
   positional argument.

#### `tests/ingestion/test_postgres_writer.py`

Unit tests for `RawLineStatusWriter` using a fake async connection
factory injected via constructor (or `monkeypatch` of
`psycopg.AsyncConnection.connect`):

1. `test_insert_binds_envelope_columns_in_order` — assert SQL +
   parameter tuple matches `INSERT_RAW_LINE_STATUS_SQL`.
2. `test_insert_returns_rowcount` — fake cursor `rowcount=1`, then
   `rowcount=0`; assert return values match.
3. `test_payload_is_serialised_via_jsonb` — assert the 5th positional
   parameter is a `Jsonb` instance whose payload equals
   `event.payload.model_dump(mode="json")`.
4. `test_reconnect_closes_and_reopens` — mock
   `psycopg.AsyncConnection.connect` with a counter; assert two
   connect calls after one `reconnect()`.

#### `tests/ingestion/integration/test_consumer_smoke.py`

One marked-`integration` test gated on **both**
`KAFKA_BOOTSTRAP_SERVERS` and `DATABASE_URL`; skipped by default; run
via `uv run pytest -m integration`.

```python
@pytest.mark.integration
async def test_consume_one_event_against_local_stack() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not set")

    event = _build_sample_event()  # unique event_id per run
    async with KafkaEventProducer(bootstrap_servers=bootstrap) as producer:
        await producer.publish(
            LineStatusEvent.TOPIC_NAME,
            event=event,
            key=event.payload.line_id,
        )

    async with (
        KafkaEventConsumer(
            LineStatusEvent.TOPIC_NAME,
            bootstrap_servers=bootstrap,
            group_id=f"smoke-{event.event_id}",
        ) as kafka,
        RawLineStatusWriter(dsn) as writer,
    ):
        consumer = LineStatusConsumer(kafka_consumer=kafka, writer=writer)
        await asyncio.wait_for(consumer.run_once(max_messages=1), timeout=10.0)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM raw.line_status WHERE event_id = %s",
            (event.event_id,),
        )
        assert cur.fetchone() == (1,)
```

`_build_sample_event` mints a fresh UUIDv4 per run so reruns do not
collide on the PK. Cleanup is best-effort (the seeded row stays — the
test is hermetic-by-uniqueness rather than hermetic-by-rollback to
match the existing TM-B2 smoke style).

`pyproject.toml:67` already filters out `integration` from the default
suite (`addopts = "-m 'not integration'"`).

### Phase 3.7 — Verification gate

Per napkin §Execution#5, all four must exit 0 before push:

```bash
uv run task lint                                  # ruff + format-check + mypy strict
uv run task test                                  # default suite (excludes integration)
uv run bandit -r src --severity-level high        # HIGH severity only
make check                                        # lint + test + dbt-parse + TS lint + TS build
```

Optional integration smoke (manual; requires `make up`,
`make init-topics`, plus the producer running so the topic has a few
events):

```bash
docker compose --profile ingest up tfl-line-status-producer -d
KAFKA_BOOTSTRAP_SERVERS=localhost:19092 \
  DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \
  uv run pytest -m integration tests/ingestion/integration/test_consumer_smoke.py
```

Mypy strict: every signature on the new modules is fully annotated.
The `consumer_factory` parameter on `KafkaEventConsumer` is typed as
`Callable[..., AIOKafkaConsumer]` and is `None` by default (resolved
to the real `AIOKafkaConsumer` constructor in `__aenter__`).

### Phase 3.8 — PR

Branch: `feature/TM-B3-line-status-consumer`. PR title:
`feat(ingestion): TM-B3 line-status consumer to Postgres (TM-8)`.

PR body (English, per CLAUDE.md §"Language and communication"):

- **Summary** — 6 bullets:
  - async `LineStatusConsumer.run_forever` reading topic
    `"line-status"` with `group_id="tfl-monitor-line-status-writer"`,
    `auto_offset_reset="earliest"`, `enable_auto_commit=False`;
  - `KafkaEventConsumer` wrapper around `AIOKafkaConsumer` (mirror of
    TM-B2's `KafkaEventProducer`);
  - `RawLineStatusWriter` over a single async psycopg connection;
    `INSERT … ON CONFLICT (event_id) DO NOTHING` for idempotency on
    replay; reconnect-on-`OperationalError`;
  - failure isolation: `pydantic.ValidationError` → skip+commit (poison
    pill); `psycopg.OperationalError` → reconnect+replay;
    unknown → log+replay; daemon never crashes;
  - lag tracing on every `kafka.consume` span; refreshed every 50 msgs
    or every 30 s via `consumer.end_offsets`;
  - Compose service `tfl-line-status-consumer` (profile `ingest`) +
    `consume-line-status` taskipy + Makefile entries; observability
    helper extracted to `src/ingestion/observability.py` (producer
    migrated in the same PR).
- **Out of scope** — arrivals/disruptions consumers (TM-B4),
  Airflow (TM-A2), prod broker / DB (TM-A3 / TM-A4), `/status/live`
  wiring (TM-D2), dbt staging (TM-C2).
- **Test plan** — command list from Phase 3.7; integration smoke
  against local Compose.
- **Closes TM-8**.

Push instructions provided to the author as text (CLAUDE.md §"Commit
rules"). Wait for required CI green + resolve any CodeRabbit / Gemini
threads (napkin §Execution#2-#3).

## Success criteria

- [ ] `src/ingestion/observability.py` created; `configure_logfire`
  helper exported and used by the producer entrypoint.
- [ ] `src/ingestion/consumers/{__init__,kafka,postgres,line_status}.py`
  implemented and importable.
- [ ] `docker-compose.yml` declares `tfl-line-status-consumer` service
  (profile `ingest`, depends on `redpanda` + `postgres` healthy).
- [ ] `pyproject.toml` declares `consume-line-status` task; `Makefile`
  declares `consume-line-status` target.
- [ ] `tests/ingestion/test_line_status_consumer.py` covers all seven
  scenarios listed in Phase 3.6.
- [ ] `tests/ingestion/test_kafka_consumer.py` covers all five
  scenarios listed in Phase 3.6.
- [ ] `tests/ingestion/test_postgres_writer.py` covers all four
  scenarios listed in Phase 3.6.
- [ ] `tests/ingestion/integration/test_consumer_smoke.py` exists,
  marked `integration`, gated on `KAFKA_BOOTSTRAP_SERVERS` +
  `DATABASE_URL`, passes manually against Compose.
- [ ] Producer test suite still passes after the
  `configure_logfire()` migration (no behavioural drift).
- [ ] `uv run task lint` passes (ruff + mypy strict on new modules).
- [ ] `uv run task test` passes (default suite excludes integration).
- [ ] `uv run bandit -r src --severity-level high` reports zero
  findings on the new consumer modules.
- [ ] `make check` passes end-to-end.
- [ ] PR opened with `Closes TM-8` in body.
- [ ] `PROGRESS.md` TM-B3 row updated to ✅ with completion date.
- [ ] `.claude/current-wp.md` updated to point at the next active WP
  (TM-B4 / TM-C2 / TM-D2 — author's call).

## Open questions (resolved during planning)

All fourteen Q1-Q14 from `TM-B3-research.md` resolved as the recommended
defaults plus the four extension points decided in chat. Trade-off
acknowledged on Q12 (extracting `src/ingestion/observability.py` adds
~15 LOC of helper plus a one-line producer diff that the producer
itself would otherwise own); kept on the ground that two ingestion
services exist now, which is exactly the trigger condition in
CLAUDE.md "Principle #1" rule 4. Trade-off acknowledged on Q11 (poison
pills are silently dropped after the warn log); kept because no DLQ
topic is provisioned and replaying the same bad message forever is a
worse outcome.

## References

- `.claude/specs/TM-B3-research.md` — surface map and open questions.
- `.claude/specs/TM-B2-plan.md` — sibling plan; pattern for the
  consumer wrapper / Compose service / test fakes.
- `.claude/napkin.md` — §Execution#5 (verification gate),
  §Domain#3 (`ingestion.foo` import style).
- `CLAUDE.md` — §"Principle #1: lean by default"; §"Pydantic usage
  conventions"; §"Observability architecture"; §"Security-first
  engineering"; §"Phase approach".
- `AGENTS.md` — §1 track inventory; §2 review checklist; §6
  dependencies (no new dep added).
- `contracts/schemas/line_status.py`, `contracts/schemas/common.py`
  (read-only, not edited).
- `contracts/sql/001_raw_tables.sql:12-22` — `raw.line_status` DDL.
- `src/ingestion/producers/{kafka,line_status}.py` — producer surface
  defining the wire format and lifecycle pattern to mirror.
- `tests/ingestion/test_kafka_producer.py` — `_FakeAIOKafkaProducer`
  pattern for the symmetric consumer fake.
- `tests/integration/test_sql_init.py:22-39` — `DATABASE_URL`-gated
  integration test pattern.
- aiokafka 0.12 docs (consulted via context7 at implementation time;
  see `AIOKafkaConsumer.commit`, `end_offsets`, async-iterator usage).
- psycopg 3 docs (consulted via context7 at implementation time; see
  `AsyncConnection.connect`, `psycopg.types.json.Jsonb`).
