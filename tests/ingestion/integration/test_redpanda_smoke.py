"""Integration smoke test producing a single ``LineStatusEvent`` to a live Redpanda.

Skipped by default; opt in via ``pytest -m integration`` against the
running Compose stack:

::

    make up
    uv run task init-topics
    uv run pytest -m integration tests/ingestion/integration/test_redpanda_smoke.py
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

from contracts.schemas import LineStatusEvent, LineStatusPayload, TransportMode
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
        valid_to=now.replace(year=now.year + 1),
    )
    return LineStatusEvent(
        event_id=uuid.uuid4(),
        event_type="line-status.snapshot",
        ingested_at=now,
        payload=payload,
    )


async def test_publish_against_local_redpanda() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    async with KafkaEventProducer(bootstrap_servers=bootstrap) as producer:
        event = _build_sample_event()
        await producer.publish(
            LineStatusEvent.TOPIC_NAME,
            event=event,
            key=event.payload.line_id,
        )
