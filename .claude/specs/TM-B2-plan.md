# TM-B2 — Implementation plan (Phase 2)

Source: `TM-B2-research.md` + author decisions on `2026-04-27`.

All ten open questions resolved as the recommended defaults from the
research file:

- **Q1 — Process model:** long-running async daemon (`asyncio.run(run_forever())`).
- **Q2 — Topic provisioning:** explicit pre-creation via a one-shot
  `rpk topic create` step wired into the Compose stack.
- **Q3 — `event_type` literal:** `"line-status.snapshot"` (room for
  future kinds without breaking consumers).
- **Q4 — Test strategy:** unit tests using `monkeypatch` against an
  in-module `AIOKafkaProducer` test double; one
  `@pytest.mark.integration` smoke test against the running Redpanda.
- **Q5 — Cadence:** fixed-rate scheduling — sleep
  `max(0.0, period_seconds - elapsed)` between cycles.
- **Q6 — Failure isolation:** retry inside the cycle on transient Kafka
  / TfL errors (mirroring TM-B1's `with_retry` posture); on permanent
  failure log + skip the cycle, never crash the daemon.
- **Q7 — `event_id`:** UUIDv4 via `uuid.uuid4()`. Document v7 as
  preferred-but-deferred (no new dependency; `raw.line_status.event_id`
  also defaults to `gen_random_uuid()` = v4).
- **Q8 — Logfire init:** inline `logfire.configure(...)` call inside
  the producer entrypoint. The `src/ingestion/observability.py`
  helper waits for the second consumer (TM-B3) to justify extraction.
- **Q9 — Compose service:** add a `tfl-line-status-producer` service
  to `docker-compose.yml`; build a minimal Python 3.12 image at
  `src/ingestion/Dockerfile`. *Trade-off acknowledged:* this adds one
  Dockerfile (~10 LOC) we did not previously need; the alternative is
  to defer containerisation to TM-A5. Default kept because `make up`
  bringing the producer up matches the SETUP.md objective end-to-end
  for the prototype.
- **Q10 — Modes:** `["tube", "elizabeth-line", "overground", "dlr"]`,
  exposed as a module-level constant `DEFAULT_LINE_STATUS_MODES` for
  easy override.

## Summary

Land the `line-status` Kafka producer under
`src/ingestion/producers/line_status.py`, plus a thin async wrapper
around `AIOKafkaProducer` under
`src/ingestion/producers/kafka.py`, plus the supporting Compose
service + topic provisioning. The producer polls
`TflClient.fetch_line_statuses(modes)` every 30 s, normalises via
`line_status_payloads`, wraps each payload into a `LineStatusEvent`
envelope, JSON-serialises through Pydantic, and produces to topic
`"line-status"` partitioned by `line_id`. Failures inside a cycle are
retried (TfL via `with_retry`, Kafka via aiokafka's built-in retries
plus a single outer try/except); the daemon never crashes on a single
bad cycle. No edits to `contracts/`. No consumer, no Postgres writes.

## Execution mode

- **Author of change:** single-track WP — execute serially in the main
  workspace (no agent-team needed; only `src/ingestion/` is touched).
- **Branch:** `feature/TM-B2-line-status-producer`.
- **PR title:** `feat(ingestion): TM-B2 line-status producer to Kafka (TM-7)`.
- **PR body:** `Closes TM-7`; lists deliverables, the cadence and
  retry policy, and the Compose / topic-provisioning approach.

## What we're NOT doing

- No consumer of `line-status`, no `raw.line_status` writes — TM-B3.
- No arrivals or disruptions producers — TM-B4.
- No Airflow DAG — TM-A2 (the daemon model in Q1 explicitly precedes
  Airflow).
- No edits to `contracts/schemas/*` or `contracts/sql/*` — frozen.
- No edits to `src/api/`, `src/agent/`, `dbt/`, `web/`, `airflow/`.
- No `Settings(BaseSettings)` class — config is two env vars
  (`KAFKA_BOOTSTRAP_SERVERS`, `TFL_APP_KEY`); CLAUDE.md "Principle #1"
  rule 5 forbids it.
- No new runtime dependency. `aiokafka>=0.12` is already in
  `pyproject.toml`; `pydantic`, `httpx`, `logfire` already in.
- No dead-letter topic — Q6 default is retry-then-skip; DLQ is
  YAGNI for the prototype.
- No UUIDv7 dependency / hand-roll — Q7 picks v4.
- No structured-logging wrapper, no custom metrics — Logfire spans
  cover what we need (CLAUDE.md "Principle #1" rules 6).
- No prod Redpanda credentials or SASL config — local dev runs
  PLAINTEXT; SASL placeholders in `.env.example` stay as-is.
- No Logfire helper module under `src/ingestion/` — Q8 keeps the
  init inline.

## Sub-phases

### Phase 3.1 — Topic provisioning

Decision Q2 picks explicit pre-creation. Add a one-shot Compose
service that runs `rpk topic create` against the broker.

`docker-compose.yml` — append after the `redpanda` service block:

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
        rpk -X brokers=redpanda:9092 topic create line-status \
          --partitions 1 --replicas 1 || true
```

Notes:

- Same Redpanda image — no new image pull.
- `profiles: ["init"]` keeps it out of the default `docker compose up`
  surface; explicit invocation: `docker compose --profile init up
  redpanda-init`.
- `|| true` makes the step idempotent (already-exists is not an
  error).
- Helper `make` target documented in Phase 3.4 below.

A separate task target wires this in:

`pyproject.toml` `[tool.taskipy.tasks]` — add:

```
init-topics = "docker compose --profile init up redpanda-init --abort-on-container-exit"
```

### Phase 3.2 — Producer module

#### `src/ingestion/producers/__init__.py`

Re-export the public surface used by tests + the entrypoint:

```python
"""Kafka producers for TfL ingestion."""

from ingestion.producers.kafka import KafkaEventProducer, KafkaProducerError
from ingestion.producers.line_status import (
    DEFAULT_LINE_STATUS_MODES,
    LINE_STATUS_EVENT_TYPE,
    LINE_STATUS_POLL_PERIOD_SECONDS,
    LineStatusProducer,
    run_forever,
)

__all__ = [
    "DEFAULT_LINE_STATUS_MODES",
    "KafkaEventProducer",
    "KafkaProducerError",
    "LINE_STATUS_EVENT_TYPE",
    "LINE_STATUS_POLL_PERIOD_SECONDS",
    "LineStatusProducer",
    "run_forever",
]
```

#### `src/ingestion/producers/kafka.py`

Thin async wrapper around `aiokafka.AIOKafkaProducer`. Single
abstraction with one consumer = aligns with CLAUDE.md "Principle #1"
rule 4 (no premature factory).

Public surface:

```python
class KafkaProducerError(RuntimeError):
    """Raised when the Kafka producer cannot publish an event."""


class KafkaEventProducer:
    """Async JSON Kafka producer wrapping ``AIOKafkaProducer``."""

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client_id: str = "tfl-monitor-ingestion",
        producer_factory: Callable[..., AIOKafkaProducer] | None = None,
    ) -> None: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def publish(
        self,
        topic: str,
        *,
        event: BaseModel,
        key: str | None,
    ) -> None:
        """Serialise ``event`` to JSON and produce it to ``topic``.

        ``key`` is encoded as UTF-8 bytes when provided so Kafka
        partitions consistently on it. ``event`` is serialised via
        Pydantic v2's ``model_dump_json()``.
        """
```

Implementation details:

- Constructor stores `bootstrap_servers` + `client_id`. Defers the
  actual `AIOKafkaProducer` instantiation to `__aenter__` so a
  test double via `producer_factory` can replace the underlying
  client without touching `aiokafka` imports.
- `__aenter__` builds the underlying producer
  (`producer_factory(bootstrap_servers=..., client_id=...,
  enable_idempotence=True, acks="all", linger_ms=10)` — `acks=all`
  is safe for a single-partition local topic and trades a few ms of
  latency for durability) and calls `await producer.start()`.
- `__aexit__` calls `await producer.stop()`.
- `publish` calls
  `await self._producer.send_and_wait(topic, value=event.model_dump_json().encode("utf-8"), key=key.encode("utf-8") if key else None)`
  inside `logfire.span("kafka.publish", topic=topic, key=key,
  event_type=event.__class__.__name__)`. On
  `aiokafka.errors.KafkaError`, raise `KafkaProducerError(...) from
  exc`.

`enable_idempotence=True` requires `acks="all"`; both are aiokafka 0.12
defaults-friendly. No retry config beyond aiokafka's built-in (the
outer cycle in `LineStatusProducer.run_once` catches and skips).

#### `src/ingestion/producers/line_status.py`

Constants:

```python
LINE_STATUS_EVENT_TYPE = "line-status.snapshot"
LINE_STATUS_POLL_PERIOD_SECONDS = 30.0
DEFAULT_LINE_STATUS_MODES: tuple[str, ...] = (
    "tube",
    "elizabeth-line",
    "overground",
    "dlr",
)
```

Class:

```python
class LineStatusProducer:
    """Polls TfL line-status and produces ``LineStatusEvent`` to Kafka."""

    def __init__(
        self,
        *,
        tfl_client: TflClient,
        kafka_producer: KafkaEventProducer,
        modes: Sequence[str] = DEFAULT_LINE_STATUS_MODES,
        period_seconds: float = LINE_STATUS_POLL_PERIOD_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        event_id_factory: Callable[[], UUID] = uuid.uuid4,
    ) -> None: ...

    async def run_once(self) -> int:
        """Fetch one TfL snapshot and publish all derived events.

        Returns the number of events successfully published. On any
        recoverable failure (TfL error, Kafka error), logs via Logfire
        and returns ``0`` — never raises.
        """

    async def run_forever(self) -> NoReturn:
        """Run ``run_once`` on a fixed-rate cadence forever."""
```

`run_once` implementation (sketch):

```python
async def run_once(self) -> int:
    try:
        tier1 = await self._tfl_client.fetch_line_statuses(self._modes)
    except TflClientError as exc:
        logfire.warn("ingestion.line_status.tfl_failed", error=repr(exc))
        return 0

    payloads = line_status_payloads(tier1)
    published = 0
    for payload in payloads:
        event = LineStatusEvent(
            event_id=self._event_id_factory(),
            event_type=LINE_STATUS_EVENT_TYPE,
            ingested_at=self._clock(),
            payload=payload,
        )
        try:
            await self._kafka_producer.publish(
                LineStatusEvent.TOPIC_NAME,
                event=event,
                key=payload.line_id,
            )
            published += 1
        except KafkaProducerError as exc:
            logfire.warn(
                "ingestion.line_status.kafka_failed",
                line_id=payload.line_id,
                error=repr(exc),
            )
    logfire.info("ingestion.line_status.cycle", published=published)
    return published
```

`run_forever` (fixed-rate):

```python
async def run_forever(self) -> NoReturn:
    while True:
        started = time.monotonic()
        await self.run_once()
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(0.0, self._period_seconds - elapsed))
```

Module-level entrypoint (used by `python -m ingestion.producers.line_status`):

```python
async def _amain() -> None:
    logfire.configure(
        service_name="tfl-monitor-ingestion",
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_httpx()

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    async with (
        TflClient.from_env() as tfl,
        KafkaEventProducer(bootstrap_servers=bootstrap) as kafka,
    ):
        producer = LineStatusProducer(tfl_client=tfl, kafka_producer=kafka)
        await producer.run_forever()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
```

Notes:

- The `clock` and `event_id_factory` injection points exist purely for
  deterministic unit tests; runtime defaults are `datetime.now(UTC)` /
  `uuid.uuid4`.
- `LineStatusEvent` does not pin the `event_type` literal in the
  contract; we set `LINE_STATUS_EVENT_TYPE = "line-status.snapshot"`
  here and keep it stable. Document this in the module docstring so
  TM-B3 knows what to filter on.
- Partition key = `payload.line_id` — guarantees per-line events stay
  ordered.

### Phase 3.3 — Compose service

`docker-compose.yml` — append after `redpanda-console`:

```yaml
  tfl-line-status-producer:
    build:
      context: .
      dockerfile: src/ingestion/Dockerfile
    restart: unless-stopped
    depends_on:
      redpanda:
        condition: service_healthy
    environment:
      TFL_APP_KEY: ${TFL_APP_KEY:?TFL_APP_KEY is required}
      KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
      LOGFIRE_TOKEN: ${LOGFIRE_TOKEN:-}
      ENVIRONMENT: ${ENVIRONMENT:-local}
      APP_VERSION: ${APP_VERSION:-0.0.1}
    command: ["uv", "run", "python", "-m", "ingestion.producers.line_status"]
```

Notes:

- `${TFL_APP_KEY:?...}` is fail-loud — Compose refuses to start the
  service without the secret (CLAUDE.md §"Security-first": never
  hardcode, never accept default-empty).
- `KAFKA_BOOTSTRAP_SERVERS=redpanda:9092` uses the internal listener
  inside the Compose network (the `19092` external listener is for
  host-side dev only).

`src/ingestion/Dockerfile` (new, ~12 LOC):

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.7

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY contracts ./contracts

ENV PYTHONPATH=/app/src

CMD ["uv", "run", "python", "-m", "ingestion.producers.line_status"]
```

Image stays slim: only the `[project]` runtime deps, no `[dependency-groups]
dev`. `PYTHONPATH=/app/src` matches the local-dev `pythonpath = ["src"]`
config and the `from ingestion.foo` import convention (napkin
Domain#3).

`Makefile` — add a target:

```
ingest-line-status: ## Run line-status producer locally (host-side, against Compose Redpanda)
	uv run python -m ingestion.producers.line_status
```

Total Makefile target count after this WP: 9 (`help`, `bootstrap`,
`up`, `down`, `clean`, `check`, `seed`, `openapi-ts`,
`sync-dbt-sources`, `ingest-line-status`) — well under the 15-target
ceiling in CLAUDE.md "Principle #1" rule 2.

### Phase 3.4 — Tests

#### `tests/ingestion/test_line_status_producer.py`

Unit tests using a Kafka producer test double + a deterministic clock
+ a deterministic UUID factory.

Test double (helper at top of the file or in
`tests/ingestion/conftest.py`):

```python
class _CapturingKafkaProducer:
    """Captures every ``publish`` call for assertion in tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def publish(
        self,
        topic: str,
        *,
        event: BaseModel,
        key: str | None,
    ) -> None:
        self.calls.append(
            {"topic": topic, "event": event, "key": key},
        )
```

Tests:

1. `test_run_once_publishes_one_event_per_payload` — feeds the
   multi-mode fixture via `httpx.MockTransport`, asserts every
   `LineStatusPayload` returned by `line_status_payloads(...)` produced
   exactly one `publish` call to topic `"line-status"`, with
   `key == payload.line_id` and `event.event_type == "line-status.snapshot"`.
2. `test_run_once_uses_injected_clock_and_event_id` — asserts the
   `ingested_at` and `event_id` fields on each captured event match
   the injected `clock` / `event_id_factory` outputs.
3. `test_run_once_handles_tfl_failure` — `TflClient` raises
   `TflClientError` on fetch; `run_once` returns `0`; no `publish`
   calls.
4. `test_run_once_continues_after_kafka_failure_for_one_line` —
   `_CapturingKafkaProducer.publish` raises `KafkaProducerError` for
   the first call; `run_once` returns `len(payloads) - 1`; remaining
   payloads are still published.
5. `test_run_forever_respects_period_and_terminates_on_cancel` —
   `monkeypatch` `asyncio.sleep` to record sleep durations; cancel the
   task after 3 cycles; assert recorded sleeps are
   `period - elapsed`-style values (positive, bounded by `period`).
6. `test_event_envelope_serialises_to_valid_json` — round-trip a
   captured `LineStatusEvent` through `event.model_dump_json()` →
   `LineStatusEvent.model_validate_json(...)` and compare; covers the
   wire format end-to-end.

#### `tests/ingestion/test_kafka_producer.py`

Unit tests for the `KafkaEventProducer` wrapper using a fake
`AIOKafkaProducer`:

```python
class _FakeAIOKafkaProducer:
    def __init__(self, **_: Any) -> None:
        self.started = False
        self.stopped = False
        self.sent: list[dict[str, Any]] = []
        self.fail_next: Exception | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(
        self, topic: str, *, value: bytes, key: bytes | None
    ) -> None:
        if self.fail_next is not None:
            raise self.fail_next
        self.sent.append({"topic": topic, "value": value, "key": key})
```

Tests:

1. `test_publish_serialises_event_via_pydantic_json` — assert
   `value == event.model_dump_json().encode("utf-8")`.
2. `test_publish_passes_key_as_utf8_bytes`.
3. `test_publish_omits_key_when_none`.
4. `test_publish_translates_kafka_error_to_kafka_producer_error` —
   inject `aiokafka.errors.KafkaError`; assert `KafkaProducerError`.
5. `test_aenter_starts_and_aexit_stops_producer`.

#### `tests/ingestion/integration/test_redpanda_smoke.py`

One marked-`integration` test producing a single
`LineStatusEvent` against the running Compose `redpanda` broker and
asserting `await producer.send_and_wait(...)` returns without error.
Skipped by default; run via `uv run pytest -m integration`.

```python
@pytest.mark.integration
async def test_publish_against_local_redpanda() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    async with KafkaEventProducer(bootstrap_servers=bootstrap) as producer:
        event = _build_sample_event()
        await producer.publish(
            LineStatusEvent.TOPIC_NAME,
            event=event,
            key=event.payload.line_id,
        )
```

Use a helper `_build_sample_event` that constructs a minimal valid
`LineStatusEvent` so the test does not depend on a live TfL response.

### Phase 3.5 — Verification gate

Per napkin §Execution#5, all four must exit 0 before push:

```bash
uv run task lint                                  # ruff + format-check + mypy strict
uv run task test                                  # default suite (excludes integration)
uv run bandit -r src --severity-level high        # HIGH severity only
make check                                        # lint + test + dbt-parse + TS lint + TS build
```

Optional integration smoke (manual; requires `make up` + `make
init-topics`):

```bash
docker compose --profile init up redpanda-init --abort-on-container-exit
uv run pytest -m integration tests/ingestion/integration/test_redpanda_smoke.py
```

Mypy strict: every signature on the new modules is fully annotated.
The `producer_factory` parameter on `KafkaEventProducer` is typed as
`Callable[..., AIOKafkaProducer]` and is `None` by default (resolved
to a real `AIOKafkaProducer` constructor in `__aenter__`).

### Phase 3.6 — PR

Branch: `feature/TM-B2-line-status-producer`. PR title:
`feat(ingestion): TM-B2 line-status producer to Kafka (TM-7)`.

PR body (English, per CLAUDE.md §"Language and communication"):

- **Summary** — 5 bullets:
  - async `LineStatusProducer` polling every 30 s, fixed-rate cadence;
  - `KafkaEventProducer` wrapper around `AIOKafkaProducer`
    (`enable_idempotence=True`, `acks="all"`, partition key =
    `line_id`);
  - `LineStatusEvent` envelope with
    `event_type = "line-status.snapshot"`, UUIDv4 `event_id`;
  - Compose service `tfl-line-status-producer` + `redpanda-init`
    profile + `src/ingestion/Dockerfile`;
  - failure isolation: TfL / Kafka errors logged + skipped, daemon
    never crashes.
- **Out of scope** — consumer (TM-B3), arrivals/disruptions (TM-B4),
  Airflow (TM-A2), prod broker (TM-A4).
- **Test plan** — command list from Phase 3.5; integration smoke
  against local Redpanda.
- **Closes TM-7**.

Push instructions provided to the author as text (CLAUDE.md §"Commit
rules"). Wait for required CI green + resolve any CodeRabbit / Gemini
threads (napkin §Execution#2-#3).

## Success criteria

- [ ] `src/ingestion/producers/{__init__,kafka,line_status}.py`
  implemented and importable.
- [ ] `src/ingestion/Dockerfile` builds; `docker compose build
  tfl-line-status-producer` succeeds.
- [ ] `docker-compose.yml` declares `redpanda-init` (profile `init`)
  and `tfl-line-status-producer` services.
- [ ] `pyproject.toml` declares `init-topics` task; `Makefile`
  declares `ingest-line-status` target.
- [ ] `tests/ingestion/test_line_status_producer.py` covers all six
  scenarios listed in Phase 3.4.
- [ ] `tests/ingestion/test_kafka_producer.py` covers all five
  scenarios listed in Phase 3.4.
- [ ] `tests/ingestion/integration/test_redpanda_smoke.py` exists,
  marked `integration`, passes manually against Compose.
- [ ] `uv run task lint` passes (ruff + mypy strict on new modules).
- [ ] `uv run task test` passes (default suite excludes integration).
- [ ] `uv run bandit -r src --severity-level high` reports zero
  findings on the new producer modules.
- [ ] `make check` passes end-to-end.
- [ ] PR opened with `Closes TM-7` in body.
- [ ] `PROGRESS.md` TM-B2 row updated to ✅ with completion date.
- [ ] `.claude/current-wp.md` updated to point at the next active WP
  (TM-B3 in serial mode, or whatever the author selects).

## Open questions (resolved during planning)

All ten Q1-Q10 from `TM-B2-research.md` resolved as the recommended
defaults. Trade-off acknowledged on Q9 (new `src/ingestion/Dockerfile`
adds ~12 LOC of containerisation that TM-A5 would otherwise own); kept
on the ground that `make up` bringing the full local pipeline up is
the most useful prototype state and we avoid splitting the Compose
work twice.

## References

- `.claude/specs/TM-B2-research.md` — surface map and open questions.
- `.claude/specs/TM-B1-plan.md` — plan template + retry / observability
  precedents.
- `.claude/napkin.md` — §Execution#5 (verification gate),
  §Execution#1 (worktree caveat — N/A here, single-track),
  §Domain#3 (`ingestion.foo` import style).
- `CLAUDE.md` — §"Principle #1: lean by default"; §"Pydantic usage
  conventions"; §"Observability architecture"; §"Security-first
  engineering".
- `AGENTS.md` — §1 track inventory; §2 review checklist.
- `contracts/schemas/line_status.py`, `contracts/schemas/common.py`
  (read-only, not edited).
- aiokafka 0.12 docs (consulted via context7 at implementation time;
  no specific API quirks anticipated since 0.12 is stable).
