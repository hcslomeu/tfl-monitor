"""Integration smoke for the line-status consumer against a live stack.

Skipped by default; opt in via ``pytest -m integration`` against the
running Compose stack with the topic seeded by the producer:

::

    make up
    uv run task init-topics
    docker compose --profile ingest up tfl-line-status-producer -d
    KAFKA_BOOTSTRAP_SERVERS=localhost:19092 \\
      DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \\
      uv run pytest -m integration tests/ingestion/integration/test_consumer_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from contracts.schemas import LineStatusEvent, LineStatusPayload, TransportMode
from ingestion.consumers import (
    KafkaEventConsumer,
    LineStatusConsumer,
    RawLineStatusWriter,
)
from ingestion.producers import KafkaEventProducer

pytestmark = pytest.mark.integration


def _build_sample_event() -> LineStatusEvent:
    now = datetime.now(UTC)
    payload = LineStatusPayload(
        line_id="victoria",
        line_name="Victoria",
        mode=TransportMode.TUBE,
        status_severity=10,
        status_severity_description="Good Service",
        reason=None,
        valid_from=now,
        valid_to=now + timedelta(days=1),
    )
    return LineStatusEvent(
        event_id=uuid.uuid4(),
        event_type="line-status.snapshot",
        ingested_at=now,
        payload=payload,
    )


async def test_consume_one_event_against_local_stack() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not set")

    event = _build_sample_event()
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
