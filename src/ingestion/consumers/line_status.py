"""TfL ``line-status`` Kafka → Postgres consumer entrypoint.

Wires :class:`ingestion.consumers.RawEventConsumer` to
:class:`contracts.schemas.LineStatusEvent` and ``raw.line_status``.
The shared loop logic, lag tracing, and failure isolation live in
:mod:`ingestion.consumers.event_consumer` so all three topic
consumers (line-status, arrivals, disruptions) share one source of
truth.
"""

from __future__ import annotations

import asyncio
import os

from contracts.schemas import LineStatusEvent
from ingestion.consumers.event_consumer import RawEventConsumer
from ingestion.consumers.kafka import KafkaEventConsumer
from ingestion.consumers.postgres import RawEventWriter
from ingestion.observability import configure_logfire

__all__ = [
    "LINE_STATUS_CONSUMER_GROUP_ID",
    "LINE_STATUS_LOG_NAMESPACE",
    "LINE_STATUS_TABLE",
    "LINE_STATUS_TOPIC_LABEL",
    "main",
]

LINE_STATUS_CONSUMER_GROUP_ID = "tfl-monitor-line-status-writer"
LINE_STATUS_TABLE = "raw.line_status"
LINE_STATUS_TOPIC_LABEL = "line-status"
# Preserved from TM-B3: the historical Logfire namespace uses an underscore
# (``ingestion.line_status.*``) even though the Kafka topic name is the
# hyphenated ``line-status``. Migrating to the generic consumer must not
# silently rename log keys downstream alerts may already match on.
LINE_STATUS_LOG_NAMESPACE = "line_status"
_LINE_STATUS_CLIENT_ID = "tfl-monitor-ingestion-line-status-consumer"


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
            client_id=_LINE_STATUS_CLIENT_ID,
        ) as kafka,
        RawEventWriter(dsn, table=LINE_STATUS_TABLE) as writer,
    ):
        consumer = RawEventConsumer[LineStatusEvent](
            kafka_consumer=kafka,
            writer=writer,
            event_class=LineStatusEvent,
            topic_label=LINE_STATUS_TOPIC_LABEL,
            log_namespace=LINE_STATUS_LOG_NAMESPACE,
        )
        await consumer.run_forever()


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.consumers.line_status``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
