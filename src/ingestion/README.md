# src/ingestion/

The streaming half: an async TfL client, three Kafka producers, and three
consumers writing JSONB rows into `raw.*`. Every byte that crosses the wire
is a Pydantic v2 model.

## Layout

```text
src/ingestion/
├─ Dockerfile               # ARM64 slim image (rebuilt by GHA matrix)
├─ observability.py         # Logfire span helpers + namespace overrides
├─ tfl_client/
│  ├─ client.py             # async httpx with hand-rolled retry
│  ├─ retry.py              # 429/5xx/timeout backoff
│  └─ normalise.py          # tier-1 → tier-2 transformations
├─ producers/
│  ├─ kafka.py              # KafkaEventProducer wrapper (acks=all, idempotent)
│  ├─ line_status.py        # 30s cadence, partition key=line_id
│  ├─ arrivals.py           # 30s cadence × 5 NaPTAN hubs
│  └─ disruptions.py        # 300s cadence × 4 modes
└─ consumers/
   ├─ kafka.py              # KafkaEventConsumer wrapper
   ├─ event_consumer.py     # generic RawEventConsumer[E]
   ├─ postgres.py           # RawEventWriter — INSERT … ON CONFLICT (event_id) DO NOTHING
   ├─ line_status.py        # binds the generic consumer to the line-status topic
   ├─ arrivals.py
   └─ disruptions.py
```

## Producer cadences

| Producer | Cadence | Partition key | Event type |
|----------|---------|---------------|------------|
| `LineStatusProducer` | 30 s | `line_id` | `line-status.snapshot` |
| `ArrivalsProducer` | 30 s × 5 hubs | `station_id` | `arrivals.snapshot` |
| `DisruptionsProducer` | 300 s × 4 modes | `disruption_id` | `disruptions.snapshot` |

All three share the `KafkaEventProducer` wrapper — `acks="all"`,
`enable_idempotence=true`, UUIDv4 `event_id`. A retry never duplicates a row.

## Consumer guarantees

| Failure | Handling |
|---------|----------|
| Poison pill (decode error) | Skip + commit |
| Transient `OperationalError` | Reconnect + replay offset |
| Unknown exception | Log + replay offset |

Idempotency comes from `INSERT … ON CONFLICT (event_id) DO NOTHING` — a
replay of a successful offset is a no-op at the row level.

Lag is computed on every `kafka.consume` span and refreshed every
**50 messages or 30 s** (whichever comes first).

## Run locally

```bash
make up                       # boots Postgres + Redpanda + Airflow
make seed                     # loads fixtures
uv run task init-topics       # creates Redpanda topics

# In separate terminals:
uv run task ingest-line-status     uv run task consume-line-status
uv run task ingest-arrivals        uv run task consume-arrivals
uv run task ingest-disruptions     uv run task consume-disruptions
```

## Run in production

TM-A5 collapses the six daemons into **two processes** so the EC2 box only
runs two ingestion containers:

```python
# src/ingestion/run_producers.py (TM-A5)
async def main() -> None:
    await asyncio.gather(
        LineStatusProducer().run_forever(),
        ArrivalsProducer().run_forever(),
        DisruptionsProducer().run_forever(),
    )
```

`run_consumers.py` mirrors. The existing producer/consumer classes are
untouched — only the entrypoint changes.

## Observability

`observability.py` exposes per-topic span namespaces and **redacts the
`app_key`** before any span is emitted. Logfire instruments httpx
automatically, so the redaction guards against the auto-instrumented spans
as well.

```python
@logfire.instrument(
    "ingestion.line_status.poll",
    record_return=False,                 # payload is large; we record metadata
)
async def fetch_line_status(self) -> tier1.LineStatusResponse:
    ...
```

## Tests

| Layer | Count |
|-------|-------|
| `tfl_client` (retry, normalise, redaction) | 14 |
| Producers (×3) | 21 |
| Consumers (×3, parametrised) | 28 |
| Integration smokes (Redpanda + Postgres) | 4 |

Total ~70 unit tests. Fixtures live under `tests/fixtures/tfl/` — tests
never hit the live TfL API.
