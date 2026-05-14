"""Single-process entrypoint running every TfL consumer concurrently.

Collapses the three per-topic consumer entrypoints (``line_status``,
``arrivals``, ``disruptions``) into one ``asyncio.gather`` so the
shared Lightsail box only runs one Python process instead of three.

Each consumer keeps its own Kafka group_id + Postgres writer (the
writers cannot be shared because they target distinct ``raw.*``
tables), so we still spin up three ``KafkaEventConsumer`` +
``RawEventWriter`` pairs — they just live inside the same event loop.

The per-topic ``main`` entrypoints remain available for local dev and
backwards compatibility.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from typing import NoReturn

import logfire

from contracts.schemas import ArrivalEvent, DisruptionEvent, LineStatusEvent
from ingestion.consumers.arrivals import (
    ARRIVALS_CONSUMER_GROUP_ID,
    ARRIVALS_TABLE,
    ARRIVALS_TOPIC_LABEL,
)
from ingestion.consumers.disruptions import (
    DISRUPTIONS_CONSUMER_GROUP_ID,
    DISRUPTIONS_TABLE,
    DISRUPTIONS_TOPIC_LABEL,
)
from ingestion.consumers.event_consumer import RawEventConsumer
from ingestion.consumers.kafka import KafkaEventConsumer
from ingestion.consumers.line_status import (
    LINE_STATUS_CONSUMER_GROUP_ID,
    LINE_STATUS_LOG_NAMESPACE,
    LINE_STATUS_TABLE,
    LINE_STATUS_TOPIC_LABEL,
)
from ingestion.consumers.postgres import RawEventWriter
from ingestion.observability import configure_logfire


async def _amain() -> NoReturn:
    configure_logfire(instrument_psycopg=True)

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    async with AsyncExitStack() as stack:
        line_status_kafka = await stack.enter_async_context(
            KafkaEventConsumer(
                LineStatusEvent.TOPIC_NAME,
                bootstrap_servers=bootstrap,
                group_id=LINE_STATUS_CONSUMER_GROUP_ID,
                client_id="tfl-monitor-ingestion-line-status-consumer",
            )
        )
        line_status_writer = await stack.enter_async_context(
            RawEventWriter(dsn, table=LINE_STATUS_TABLE)
        )
        arrivals_kafka = await stack.enter_async_context(
            KafkaEventConsumer(
                ArrivalEvent.TOPIC_NAME,
                bootstrap_servers=bootstrap,
                group_id=ARRIVALS_CONSUMER_GROUP_ID,
                client_id="tfl-monitor-ingestion-arrivals-consumer",
            )
        )
        arrivals_writer = await stack.enter_async_context(RawEventWriter(dsn, table=ARRIVALS_TABLE))
        disruptions_kafka = await stack.enter_async_context(
            KafkaEventConsumer(
                DisruptionEvent.TOPIC_NAME,
                bootstrap_servers=bootstrap,
                group_id=DISRUPTIONS_CONSUMER_GROUP_ID,
                client_id="tfl-monitor-ingestion-disruptions-consumer",
            )
        )
        disruptions_writer = await stack.enter_async_context(
            RawEventWriter(dsn, table=DISRUPTIONS_TABLE)
        )

        line_status_consumer = RawEventConsumer[LineStatusEvent](
            kafka_consumer=line_status_kafka,
            writer=line_status_writer,
            event_class=LineStatusEvent,
            topic_label=LINE_STATUS_TOPIC_LABEL,
            log_namespace=LINE_STATUS_LOG_NAMESPACE,
        )
        arrivals_consumer = RawEventConsumer[ArrivalEvent](
            kafka_consumer=arrivals_kafka,
            writer=arrivals_writer,
            event_class=ArrivalEvent,
            topic_label=ARRIVALS_TOPIC_LABEL,
        )
        disruptions_consumer = RawEventConsumer[DisruptionEvent](
            kafka_consumer=disruptions_kafka,
            writer=disruptions_writer,
            event_class=DisruptionEvent,
            topic_label=DISRUPTIONS_TOPIC_LABEL,
        )
        logfire.info("ingestion.run_consumers.start", count=3)
        # TaskGroup (Python 3.11+) propagates the first failure as an
        # ExceptionGroup and cancels the surviving consumers, so the
        # box's process supervisor (Docker restart=unless-stopped)
        # restarts the whole bundle cleanly.
        async with asyncio.TaskGroup() as tg:
            tg.create_task(line_status_consumer.run_forever())
            tg.create_task(arrivals_consumer.run_forever())
            tg.create_task(disruptions_consumer.run_forever())

    raise AssertionError("run_forever loops never return")


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.run_consumers``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
