"""TfL ``arrivals`` Kafka → Postgres consumer entrypoint.

Wires :class:`ingestion.consumers.RawEventConsumer` to
:class:`contracts.schemas.ArrivalEvent` and ``raw.arrivals``.
"""

from __future__ import annotations

import asyncio
import os

from contracts.schemas import ArrivalEvent
from ingestion.consumers.event_consumer import RawEventConsumer
from ingestion.consumers.kafka import KafkaEventConsumer
from ingestion.consumers.postgres import RawEventWriter
from ingestion.observability import configure_logfire

__all__ = [
    "ARRIVALS_CONSUMER_GROUP_ID",
    "ARRIVALS_TABLE",
    "ARRIVALS_TOPIC_LABEL",
    "main",
]

ARRIVALS_CONSUMER_GROUP_ID = "tfl-monitor-arrivals-writer"
ARRIVALS_TABLE = "raw.arrivals"
ARRIVALS_TOPIC_LABEL = "arrivals"
_ARRIVALS_CLIENT_ID = "tfl-monitor-ingestion-arrivals-consumer"


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
            client_id=_ARRIVALS_CLIENT_ID,
        ) as kafka,
        RawEventWriter(dsn, table=ARRIVALS_TABLE) as writer,
    ):
        consumer = RawEventConsumer[ArrivalEvent](
            kafka_consumer=kafka,
            writer=writer,
            event_class=ArrivalEvent,
            topic_label=ARRIVALS_TOPIC_LABEL,
        )
        await consumer.run_forever()


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.consumers.arrivals``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
