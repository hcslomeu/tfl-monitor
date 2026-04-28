# TM-B4 — Implementation plan (Phase 2)

Source: `TM-B4-research.md` + recommended defaults applied for every
open question (Q1–Q12) per CLAUDE.md "Principle #1: lean by default".

All twelve open questions resolved as the recommended defaults from
the research file:

- **Q1 — Arrival stops**: five major-hub NaPTAN ids exposed as
  `DEFAULT_ARRIVAL_STOPS`.
- **Q2 — Disruption modes**: `("tube", "elizabeth-line", "overground",
  "dlr")`, parity with line-status.
- **Q3 — Cadence**: arrivals 30 s, disruptions 300 s.
- **Q4 — Partition keys**: `payload.station_id` for arrivals,
  `payload.disruption_id` for disruptions.
- **Q5 — Generalisation**: introduce
  `RawEventConsumer[E]` + `RawEventWriter`; migrate line-status in
  the same PR (TM-B3 observability-helper precedent).
- **Q6 — Event types**: `"arrivals.snapshot"`,
  `"disruptions.snapshot"`.
- **Q7 — Consumer groups**: `tfl-monitor-arrivals-writer`,
  `tfl-monitor-disruptions-writer`.
- **Q8 — Tests**: per-topic producer test files + a single
  parametrised generic consumer test file replacing
  `test_line_status_consumer.py`.
- **Q9 — Compose**: four new services, profile `ingest`.
- **Q10 — Idempotency**: SQL-level via `ON CONFLICT (event_id) DO
  NOTHING`; fresh `event_id` per cycle. Dedup in dbt (TM-C3) on
  natural keys (`arrival_id`, `disruption_id`).
- **Q11 — Stop fan-out**: sequential.
- **Q12 — `.env.example`**: no change; existing
  `TFL_APP_KEY` / Postgres vars cover the new services.

## Summary

Land arrivals + disruptions Kafka producers and Postgres consumers
under `src/ingestion/{producers,consumers}/`, generalising the
line-status consumer body into a `RawEventConsumer[E]` and the
line-status writer into a `RawEventWriter`. The two new producers
mirror `LineStatusProducer` (fixed-rate cadence, fail-soft logging,
deterministic clock + UUID injection points). The two new consumer
entrypoints wire the generic consumer/writer to the matching event
class + raw table. Topic provisioning is extended to create three
topics. Four new Compose services land under profile `ingest`. No
edits to `contracts/`. No new runtime dependency.

## Execution mode

- **Author of change:** single-track WP — execute serially in the
  main workspace; only `src/ingestion/`, `tests/ingestion/`,
  `docker-compose.yml`, `pyproject.toml`, `Makefile`, `PROGRESS.md`
  touched. No concurrent track.
- **Branch:** `feature/TM-B4-arrivals-disruptions`.
- **PR title:**
  `feat(ingestion): TM-B4 arrivals + disruptions producers/consumers (TM-12)`.
- **PR body:** `Closes TM-12`; lists deliverables, the
  consumer/writer generalisation, the new compose services, and the
  cadence + partition-key choices.

## What we're NOT doing

- No edits to `contracts/schemas/*` or `contracts/sql/*` — frozen.
- No DLQ topic; poison pills stay skip-and-commit (TM-B3 default).
- No `psycopg_pool` dependency — single async connection per writer.
- No dynamic stop-list discovery (Q1c) — defer to a follow-up WP if
  the dashboard needs full coverage.
- No bus-mode disruption polling (Q2b) — payload large; out of
  scope.
- No concurrent stop fan-out (Q11b) — sequential is sufficient at
  prototype scale.
- No `Settings(BaseSettings)` class — env vars stay flat
  (`TFL_APP_KEY`, `KAFKA_BOOTSTRAP_SERVERS`, `DATABASE_URL`,
  optional `LOGFIRE_TOKEN`).
- No new runtime dependency.
- No producer-side change to `LineStatusProducer` — it already works.
- No `.env.example` edits — existing vars cover the new services.
- No Airflow DAG (TM-A2), no prod broker / DB (TM-A3 / TM-A4), no
  endpoint wiring (TM-D3), no dbt staging on top of new tables
  (TM-C3), no custom metrics or DLQ.

## Sub-phases

### Phase 3.1 — Generic consumer + writer (refactor)

#### `src/ingestion/consumers/postgres.py` (revised)

Replace `RawLineStatusWriter` with a parameterised
`RawEventWriter`. The 5-column envelope DDL is identical across all
three raw tables, so the table name + event class are the only
parameters that differ.

Public surface:

```python
INSERT_RAW_EVENT_SQL_TEMPLATE = (
    "INSERT INTO {table} (event_id, ingested_at, event_type, source, payload) "
    "VALUES (%s, %s, %s, %s, %s) "
    "ON CONFLICT (event_id) DO NOTHING"
)


class RawEventWriter:
    """Owns a single async psycopg connection; writes envelopes to ``{schema}.{table}``."""

    def __init__(
        self,
        dsn: str,
        *,
        table: str,
        connection_factory: ConnectionFactory | None = None,
    ) -> None: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def insert(self, event: Event[BaseModel]) -> int: ...
    async def reconnect(self) -> None: ...
```

Implementation notes:

- `table` is validated against an allow-list of known raw tables
  (`{"raw.line_status", "raw.arrivals", "raw.disruptions"}`) at
  construction time so an attacker-controlled DSN parameter cannot
  inject SQL via the `INSERT INTO {table}` substitution.
  Parameterised values are still bound via `%s` (CLAUDE.md
  §"Security-first").
- The SQL string is built once per writer instance so the format
  expansion happens out of the hot path.
- The `Event[BaseModel]` type signature accepts any tier-2 envelope
  (`LineStatusEvent`, `ArrivalEvent`, `DisruptionEvent`).
- Body otherwise mirrors `RawLineStatusWriter`: `Jsonb(payload.model_dump(mode="json"))`,
  `logfire.span("db.insert", table=...)`, reconnect with backoff.

#### `src/ingestion/consumers/event_consumer.py` (new)

Generic consumer wrapping the previous `LineStatusConsumer` body,
parameterised on the event class to validate against.

```python
class RawEventConsumer[E: Event[Any]]:
    """Consume one Kafka topic, validate as ``event_class``, write via writer."""

    def __init__(
        self,
        *,
        kafka_consumer: KafkaEventConsumer,
        writer: RawEventWriter,
        event_class: type[E],
        topic_label: str,
        clock: Callable[[], float] = time.monotonic,
        lag_refresh_messages: int = 50,
        lag_refresh_seconds: float = 30.0,
    ) -> None: ...

    async def run_once(self, max_messages: int | None = None) -> int: ...
    async def run_forever(self) -> NoReturn: ...
```

Notes:

- `topic_label` is a short identifier (e.g. `"line-status"`,
  `"arrivals"`, `"disruptions"`) used for Logfire span attributes
  and structured-log namespacing. Keeps log lines self-describing
  even when multiple consumers run side-by-side.
- The body is the line-status consumer body verbatim, with
  `LineStatusEvent.model_validate_json` swapped for
  `event_class.model_validate_json`.
- The Logfire log namespaces become
  `f"ingestion.{topic_label}.poison_pill"`,
  `f"ingestion.{topic_label}.db_transient"`, etc.

#### `src/ingestion/consumers/line_status.py` (revised)

Becomes a 30-line entrypoint:

```python
LINE_STATUS_CONSUMER_GROUP_ID = "tfl-monitor-line-status-writer"


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
            client_id="tfl-monitor-ingestion-line-status-consumer",
        ) as kafka,
        RawEventWriter(dsn, table="raw.line_status") as writer,
    ):
        consumer = RawEventConsumer[LineStatusEvent](
            kafka_consumer=kafka,
            writer=writer,
            event_class=LineStatusEvent,
            topic_label="line-status",
        )
        await consumer.run_forever()
```

#### `src/ingestion/consumers/__init__.py` (revised)

Re-export the new generic surface; drop the line-status-specific
class names.

```python
from ingestion.consumers.event_consumer import RawEventConsumer
from ingestion.consumers.kafka import KafkaConsumerError, KafkaEventConsumer
from ingestion.consumers.postgres import RawEventWriter

__all__ = [
    "KafkaConsumerError",
    "KafkaEventConsumer",
    "RawEventConsumer",
    "RawEventWriter",
]
```

Note: `LineStatusConsumer` and `RawLineStatusWriter` symbols are
removed. Callers (only the `_amain` entrypoint and tests) update
in this PR.

### Phase 3.2 — Arrivals producer

#### `src/ingestion/producers/arrivals.py` (new)

Constants:

```python
ARRIVALS_EVENT_TYPE = "arrivals.snapshot"
ARRIVALS_POLL_PERIOD_SECONDS = 30.0
DEFAULT_ARRIVAL_STOPS: tuple[str, ...] = (
    "940GZZLUOXC",  # Oxford Circus
    "940GZZLUKSX",  # King's Cross St Pancras
    "940GZZLUWLO",  # Waterloo
    "940GZZLUBNK",  # Bank
    "940GZZLULVT",  # Liverpool Street
)
```

Class:

```python
class ArrivalsProducer:
    """Polls TfL arrivals for a fixed list of NaPTAN stop ids and produces events."""

    def __init__(
        self,
        *,
        tfl_client: TflClient,
        kafka_producer: KafkaEventProducer,
        stops: Sequence[str] = DEFAULT_ARRIVAL_STOPS,
        period_seconds: float = ARRIVALS_POLL_PERIOD_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        event_id_factory: Callable[[], UUID] = uuid.uuid4,
    ) -> None: ...

    async def run_once(self) -> int: ...
    async def run_forever(self) -> NoReturn: ...
```

`run_once` per-stop loop (sketch):

```python
async def run_once(self) -> int:
    published = 0
    for stop_id in self._stops:
        try:
            tier1 = await self._tfl_client.fetch_arrivals(stop_id)
        except TflClientError as exc:
            logfire.warn(
                "ingestion.arrivals.tfl_failed",
                stop_id=stop_id,
                error=repr(exc),
            )
            continue
        for payload in arrival_payloads(tier1):
            event = ArrivalEvent(
                event_id=self._event_id_factory(),
                event_type=ARRIVALS_EVENT_TYPE,
                ingested_at=self._clock(),
                payload=payload,
            )
            try:
                await self._kafka_producer.publish(
                    ArrivalEvent.TOPIC_NAME,
                    event=event,
                    key=payload.station_id,
                )
                published += 1
            except KafkaProducerError as exc:
                logfire.warn(
                    "ingestion.arrivals.kafka_failed",
                    stop_id=stop_id,
                    arrival_id=payload.arrival_id,
                    error=repr(exc),
                )
    logfire.info("ingestion.arrivals.cycle", published=published)
    return published
```

`run_forever` mirrors `LineStatusProducer.run_forever` (fixed-rate
cadence with overrun warning).

Module entrypoint `_amain` mirrors `producers/line_status.py:_amain`
but instantiates `ArrivalsProducer`.

#### `src/ingestion/producers/disruptions.py` (new)

Constants:

```python
DISRUPTIONS_EVENT_TYPE = "disruptions.snapshot"
DISRUPTIONS_POLL_PERIOD_SECONDS = 300.0
DEFAULT_DISRUPTION_MODES: tuple[str, ...] = (
    "tube",
    "elizabeth-line",
    "overground",
    "dlr",
)
```

Class shape mirrors `LineStatusProducer` exactly with
`disruption_payloads` and `DisruptionEvent`. Partition key =
`payload.disruption_id`.

#### `src/ingestion/producers/__init__.py` (revised)

Re-export the new producer + constants alongside the existing
line-status surface.

```python
from ingestion.producers.arrivals import (
    ARRIVALS_EVENT_TYPE,
    ARRIVALS_POLL_PERIOD_SECONDS,
    DEFAULT_ARRIVAL_STOPS,
    ArrivalsProducer,
)
from ingestion.producers.disruptions import (
    DEFAULT_DISRUPTION_MODES,
    DISRUPTIONS_EVENT_TYPE,
    DISRUPTIONS_POLL_PERIOD_SECONDS,
    DisruptionsProducer,
)
from ingestion.producers.kafka import KafkaEventProducer, KafkaProducerError
from ingestion.producers.line_status import (
    DEFAULT_LINE_STATUS_MODES,
    LINE_STATUS_EVENT_TYPE,
    LINE_STATUS_POLL_PERIOD_SECONDS,
    LineStatusProducer,
)

__all__ = [
    "ARRIVALS_EVENT_TYPE",
    "ARRIVALS_POLL_PERIOD_SECONDS",
    "ArrivalsProducer",
    "DEFAULT_ARRIVAL_STOPS",
    "DEFAULT_DISRUPTION_MODES",
    "DEFAULT_LINE_STATUS_MODES",
    "DISRUPTIONS_EVENT_TYPE",
    "DISRUPTIONS_POLL_PERIOD_SECONDS",
    "DisruptionsProducer",
    "KafkaEventProducer",
    "KafkaProducerError",
    "LINE_STATUS_EVENT_TYPE",
    "LINE_STATUS_POLL_PERIOD_SECONDS",
    "LineStatusProducer",
]
```

### Phase 3.3 — Arrivals + disruptions consumer entrypoints

#### `src/ingestion/consumers/arrivals.py` (new)

```python
ARRIVALS_CONSUMER_GROUP_ID = "tfl-monitor-arrivals-writer"


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
            ArrivalEvent.TOPIC_NAME,
            bootstrap_servers=bootstrap,
            group_id=ARRIVALS_CONSUMER_GROUP_ID,
            client_id="tfl-monitor-ingestion-arrivals-consumer",
        ) as kafka,
        RawEventWriter(dsn, table="raw.arrivals") as writer,
    ):
        consumer = RawEventConsumer[ArrivalEvent](
            kafka_consumer=kafka,
            writer=writer,
            event_class=ArrivalEvent,
            topic_label="arrivals",
        )
        await consumer.run_forever()
```

#### `src/ingestion/consumers/disruptions.py` (new)

Same shape, `DisruptionEvent` + `raw.disruptions` +
`tfl-monitor-disruptions-writer` + `topic_label="disruptions"`.

### Phase 3.4 — Topic provisioning + Compose + wiring

#### `docker-compose.yml`

Update `redpanda-init` to create three topics in one shot:

```yaml
  redpanda-init:
    image: redpandadata/redpanda:v24.2.7
    profiles: ["init"]
    depends_on:
      redpanda:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        set -e
        for topic in line-status arrivals disruptions; do
          out=$$(rpk -X brokers=redpanda:9092 topic create $$topic \
            --partitions 1 --replicas 1 2>&1) || rc=$$?
          echo "$$out"
          if [ "$${rc:-0}" -ne 0 ] && ! echo "$$out" | grep -qi "already exists\|TOPIC_ALREADY_EXISTS"; then
            exit 1
          fi
          rc=0
        done
```

Append four new services after `tfl-line-status-consumer`:

```yaml
  tfl-arrivals-producer:
    build:
      context: .
      dockerfile: src/ingestion/Dockerfile
    restart: unless-stopped
    profiles: ["ingest"]
    depends_on:
      redpanda:
        condition: service_healthy
    environment:
      TFL_APP_KEY: ${TFL_APP_KEY:?TFL_APP_KEY is required}
      KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
      LOGFIRE_TOKEN: ${LOGFIRE_TOKEN:-}
      ENVIRONMENT: ${ENVIRONMENT:-local}
      APP_VERSION: ${APP_VERSION:-0.0.1}
    command: ["uv", "run", "python", "-m", "ingestion.producers.arrivals"]

  tfl-arrivals-consumer:
    build:
      context: .
      dockerfile: src/ingestion/Dockerfile
    restart: unless-stopped
    profiles: ["ingest"]
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
    command: ["uv", "run", "python", "-m", "ingestion.consumers.arrivals"]

  tfl-disruptions-producer:
    build:
      context: .
      dockerfile: src/ingestion/Dockerfile
    restart: unless-stopped
    profiles: ["ingest"]
    depends_on:
      redpanda:
        condition: service_healthy
    environment:
      TFL_APP_KEY: ${TFL_APP_KEY:?TFL_APP_KEY is required}
      KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
      LOGFIRE_TOKEN: ${LOGFIRE_TOKEN:-}
      ENVIRONMENT: ${ENVIRONMENT:-local}
      APP_VERSION: ${APP_VERSION:-0.0.1}
    command: ["uv", "run", "python", "-m", "ingestion.producers.disruptions"]

  tfl-disruptions-consumer:
    build:
      context: .
      dockerfile: src/ingestion/Dockerfile
    restart: unless-stopped
    profiles: ["ingest"]
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
    command: ["uv", "run", "python", "-m", "ingestion.consumers.disruptions"]
```

#### `pyproject.toml` `[tool.taskipy.tasks]`

Add four entries beside the existing line-status pair:

```ini
ingest-arrivals = "python -m ingestion.producers.arrivals"
ingest-disruptions = "python -m ingestion.producers.disruptions"
consume-arrivals = "python -m ingestion.consumers.arrivals"
consume-disruptions = "python -m ingestion.consumers.disruptions"
```

#### `Makefile`

Add `consume-arrivals` and `consume-disruptions` targets mirroring
`consume-line-status`. Producer-side `make` targets are not added —
the prod-like path is via Compose. Total Makefile target count
after this WP: 12 — well under the 15-target ceiling in CLAUDE.md
"Principle #1" rule 2.

### Phase 3.5 — Tests

#### `tests/ingestion/test_arrivals_producer.py` (new)

Mirror `test_line_status_producer.py` structure with the
`arrivals_oxford_circus_fixture`. Coverage:

1. `test_run_once_publishes_one_event_per_payload` — assert
   `len(kafka.calls) == len(arrival_payloads(parsed))`, every
   call's `topic == "arrivals"`,
   `event.event_type == "arrivals.snapshot"`, `key ==
   payload.station_id`.
2. `test_run_once_uses_injected_clock_and_event_id` — single stop;
   assert deterministic `ingested_at` and `event_id`.
3. `test_run_once_handles_tfl_failure_for_one_stop` — multi-stop
   producer with first stop returning HTTP 401 (mocked); cycle
   continues, partial `published` count returned.
4. `test_run_once_continues_after_kafka_failure_for_one_arrival` —
   capturing producer raises for one `arrival_id`; rest still
   published.
5. `test_run_forever_respects_period_and_terminates_on_cancel` —
   identical pattern to the line-status test.
6. `test_event_envelope_serialises_to_valid_json` — round-trip an
   `ArrivalEvent`.
7. `test_constructor_rejects_non_positive_period`.

#### `tests/ingestion/test_disruptions_producer.py` (new)

Mirror with `disruptions_tube_fixture`. Coverage matches the arrivals
test list (1) – (7), with the partition key check switched to
`payload.disruption_id` and the event class to `DisruptionEvent`.

#### `tests/ingestion/test_event_consumer.py` (replaces `test_line_status_consumer.py`)

Generic consumer tests parametrised over the three event classes.
The body of each scenario is identical to TM-B3's
`test_line_status_consumer.py`; the parametrisation provides:

- `(event_class=LineStatusEvent, build_event=_build_line_status_event,
   topic_label="line-status", topic_name="line-status")`
- `(event_class=ArrivalEvent, build_event=_build_arrival_event,
   topic_label="arrivals", topic_name="arrivals")`
- `(event_class=DisruptionEvent, build_event=_build_disruption_event,
   topic_label="disruptions", topic_name="disruptions")`

Scenarios preserved:

1. `test_run_once_inserts_one_row_per_event`
2. `test_run_once_skips_and_commits_poison_pill`
3. `test_run_once_does_not_commit_on_db_operational_error`
4. `test_run_once_does_not_commit_on_unknown_db_error`
5. `test_commit_failure_is_swallowed_and_loop_continues`
6. `test_reconnect_failure_is_swallowed_with_replay_scheduled`
7. `test_reconnect_swallows_non_operational_error`
8. `test_duplicate_returns_zero_rowcount_but_still_commits`
9. `test_run_forever_refreshes_lag_after_n_messages`
10. `test_run_forever_refreshes_lag_after_period`

The `_FakeWriter` and `_FakeKafka` doubles move from the deleted
test file into either `tests/ingestion/conftest.py` or the new file
itself (whichever ends up cleaner — leaning toward the test file
since they are local helpers).

#### `tests/ingestion/test_postgres_writer.py` (revised)

Adapt the four scenarios to the `RawEventWriter` signature:

1. `test_insert_binds_envelope_columns_in_order` — assert SQL is
   `INSERT INTO raw.line_status …`, parameter tuple matches.
2. `test_insert_returns_rowcount`.
3. `test_payload_is_serialised_via_jsonb`.
4. `test_reconnect_closes_and_reopens`.

Plus a new scenario:
5. `test_invalid_table_is_rejected_at_construction` — ensures the
   `table` allow-list keeps SQL injection out of the format string.

The fixture `_build_event()` now produces a `LineStatusEvent`; the
arrivals/disruptions writer paths are exercised via the generic
consumer tests.

#### `tests/ingestion/integration/test_consumer_smoke.py` (revised)

Generalise the existing line-status smoke test by parametrising the
`event_class`/`writer`/`topic` combo. Run shape: produce one event,
spin up a fresh consumer with a unique `group_id`, assert the row
lands in the matching `raw.<table>`.

The integration test ID pattern stays as
`f"smoke-{event.event_id}"` so reruns don't collide on group state.

Skipped by default; opted in via `pytest -m integration`.

#### `tests/ingestion/conftest.py`

No new fixtures needed (the existing
`arrivals_oxford_circus_fixture` and `disruptions_tube_fixture` are
already published; the consumer test doubles move into the new
generic test file).

### Phase 3.6 — Verification gate

Per napkin §Execution#5, all four must exit 0 before push:

```bash
uv run task lint                                  # ruff + format-check + mypy strict
uv run task test                                  # default suite (excludes integration)
uv run bandit -r src --severity-level high        # HIGH severity only
make check                                        # lint + test + dbt-parse + TS lint + TS build
```

Manual integration smoke (requires `make up`,
`docker compose --profile init up redpanda-init --abort-on-container-exit`,
plus `--profile ingest` services running):

```bash
docker compose --profile ingest up tfl-arrivals-producer tfl-disruptions-producer -d
KAFKA_BOOTSTRAP_SERVERS=localhost:19092 \
  DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \
  uv run pytest -m integration tests/ingestion/integration/test_consumer_smoke.py
```

Mypy strict: every signature on the new modules + the generic
parameter `[E: Event[Any]]` must be fully annotated. The
`type[E]` parameter on `RawEventConsumer.__init__` is required so
`event_class.model_validate_json(...)` typechecks.

### Phase 3.7 — PR

Branch: `feature/TM-B4-arrivals-disruptions`. PR title:
`feat(ingestion): TM-B4 arrivals + disruptions producers/consumers (TM-12)`.

PR body (English, per CLAUDE.md §"Language and communication"):

- **Summary** — 6 bullets:
  - `ArrivalsProducer` polling 5 NaPTAN hubs every 30 s, partition
    key = `station_id`, `event_type = "arrivals.snapshot"`;
  - `DisruptionsProducer` polling 4 modes every 300 s, partition
    key = `disruption_id`, `event_type = "disruptions.snapshot"`;
  - generic `RawEventConsumer[E]` + `RawEventWriter(table)`
    introduced; line-status consumer/writer migrated in the same PR
    (TM-B3 observability-helper precedent);
  - four new Compose services under profile `ingest`; topic
    provisioning extended to create three topics in `redpanda-init`;
  - failure isolation unchanged from TM-B3 (poison pill = skip+commit;
    transient DB = reconnect+replay; unknown = log+replay; daemon
    never crashes);
  - lag tracing, deterministic clock + UUID injection points,
    `acks=all` + idempotent producer config — all preserved from
    TM-B2/B3.
- **Out of scope** — Airflow DAG (TM-A2), prod broker / DB
  (TM-A3 / TM-A4), `/disruptions/active` + arrivals endpoints
  (TM-D3), dbt staging/marts on top of new tables (TM-C3),
  dynamic stop discovery, bus-mode disruptions, DLQ.
- **Test plan** — command list from Phase 3.6; integration smoke
  against local Compose.
- **Closes TM-12**.

Push instructions provided to the author as text (CLAUDE.md §"Commit
rules"). Wait for required CI green + resolve any CodeRabbit /
Gemini threads (napkin §Execution#2-#3).

## Success criteria

- [ ] `src/ingestion/producers/{arrivals,disruptions}.py` implemented
  and importable.
- [ ] `src/ingestion/consumers/{arrivals,disruptions,event_consumer}.py`
  implemented and importable.
- [ ] `src/ingestion/consumers/postgres.py` exports `RawEventWriter`
  with table allow-list.
- [ ] `src/ingestion/consumers/line_status.py` migrated to use
  `RawEventConsumer` + `RawEventWriter`; `python -m
  ingestion.consumers.line_status` invocation contract preserved.
- [ ] `src/ingestion/{producers,consumers}/__init__.py` re-export
  the new public surface.
- [ ] `docker-compose.yml` `redpanda-init` creates three topics;
  four new services declared (arrivals + disruptions × producer +
  consumer), all on profile `ingest`, all building from
  `src/ingestion/Dockerfile`.
- [ ] `pyproject.toml` declares the four new taskipy tasks;
  `Makefile` declares the two new `consume-*` targets.
- [ ] `tests/ingestion/test_arrivals_producer.py` covers the seven
  scenarios listed in Phase 3.5.
- [ ] `tests/ingestion/test_disruptions_producer.py` covers the
  seven scenarios listed in Phase 3.5.
- [ ] `tests/ingestion/test_event_consumer.py` parametrises the ten
  scenarios listed in Phase 3.5 across the three event classes.
- [ ] `tests/ingestion/test_postgres_writer.py` covers the five
  scenarios listed in Phase 3.5.
- [ ] `tests/ingestion/integration/test_consumer_smoke.py`
  generalised to cover all three topics; gated on
  `KAFKA_BOOTSTRAP_SERVERS` + `DATABASE_URL`.
- [ ] `uv run task lint` passes (ruff + mypy strict on new + revised
  modules).
- [ ] `uv run task test` passes (default suite excludes integration).
- [ ] `uv run bandit -r src --severity-level high` reports zero
  findings.
- [ ] `make check` passes end-to-end.
- [ ] PR opened with `Closes TM-12` in body.
- [ ] `PROGRESS.md` TM-B4 row updated to ✅ with completion date and
  notes.
- [ ] `.claude/current-wp.md` updated to point at the next active WP
  (TM-C2 / TM-D2 / TM-E1 — author's call).

## Open questions (resolved during planning)

All twelve Q1–Q12 from `TM-B4-research.md` resolved as the recommended
defaults. Trade-off acknowledged on Q5 (generic consumer + writer
adds ~120 LOC of generalisation churn vs. ~400 LOC of duplication
across three near-identical modules); kept on the ground that the
third case is the canonical trigger for CLAUDE.md "Principle #1"
rule 4 and the line-status migration is a one-shot atomic refactor
inside the same PR.

## References

- `.claude/specs/TM-B4-research.md` — surface map and open
  questions.
- `.claude/specs/TM-B2-plan.md` — producer template (Phase 3.2).
- `.claude/specs/TM-B3-plan.md` — consumer template (Phase 3.4) +
  observability extraction precedent (Phase 3.1).
- `.claude/napkin.md` — §Execution#5 (verification gate),
  §Domain#3 (`ingestion.foo` import style).
- `CLAUDE.md` — §"Principle #1: lean by default" rules 4, 5, 6;
  §"Pydantic usage conventions"; §"Phase approach";
  §"Security-first engineering".
- `AGENTS.md` — track inventory (B-ingestion);
  §6 dependencies (no new dep added).
- `contracts/schemas/{arrivals,disruptions,common,line_status}.py`
  — frozen Pydantic shapes consumed verbatim.
- `contracts/sql/001_raw_tables.sql` — three identical raw-table
  DDLs that the `RawEventWriter` allow-list reflects.
- `src/ingestion/{producers,consumers}/*` — TM-B2 + TM-B3 surface
  extended in this WP.
- `tests/fixtures/tfl/{arrivals_oxford_circus,disruptions_tube}.json`
  — committed by TM-B1.
- aiokafka 0.12 + psycopg 3 docs (already consulted via context7
  during TM-B2/B3; no new APIs in this WP).
