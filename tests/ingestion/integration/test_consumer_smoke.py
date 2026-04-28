"""Integration smoke for ingestion consumers against a live stack.

Skipped by default; opt in via ``pytest -m integration`` against the
running Compose stack with topics seeded (the producers are the
intended source, but a one-shot publish-then-consume is sufficient
for the smoke):

::

    make up
    uv run task init-topics
    KAFKA_BOOTSTRAP_SERVERS=localhost:19092 \\
      DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \\
      uv run pytest -m integration tests/ingestion/integration/test_consumer_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from contracts.schemas import (
    ArrivalEvent,
    ArrivalPayload,
    DisruptionCategory,
    DisruptionEvent,
    DisruptionPayload,
    LineStatusEvent,
    LineStatusPayload,
    TransportMode,
)
from contracts.schemas.common import Event
from ingestion.consumers import (
    KafkaEventConsumer,
    RawEventConsumer,
    RawEventWriter,
)
from ingestion.producers import KafkaEventProducer

pytestmark = pytest.mark.integration


def _build_line_status_event() -> LineStatusEvent:
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


def _build_arrival_event() -> ArrivalEvent:
    now = datetime.now(UTC)
    payload = ArrivalPayload(
        arrival_id=f"smoke-{uuid.uuid4()}",
        station_id="940GZZLUOXC",
        station_name="Oxford Circus Underground Station",
        line_id="victoria",
        platform_name="Northbound - Platform 1",
        direction="inbound",
        destination="Walthamstow Central",
        expected_arrival=now + timedelta(seconds=120),
        time_to_station_seconds=120,
        vehicle_id="263",
    )
    return ArrivalEvent(
        event_id=uuid.uuid4(),
        event_type="arrivals.snapshot",
        ingested_at=now,
        payload=payload,
    )


def _build_disruption_event() -> DisruptionEvent:
    now = datetime.now(UTC)
    payload = DisruptionPayload(
        disruption_id=uuid.uuid4().hex,
        category=DisruptionCategory.REAL_TIME,
        category_description="RealTime",
        description="Smoke-test disruption.",
        summary="Smoke-test disruption.",
        affected_routes=["victoria"],
        affected_stops=[],
        closure_text="severeDelays",
        severity=6,
        created=now,
        last_update=now,
    )
    return DisruptionEvent(
        event_id=uuid.uuid4(),
        event_type="disruptions.snapshot",
        ingested_at=now,
        payload=payload,
    )


@dataclass(frozen=True)
class _SmokeTopic:
    label: str
    table: str
    event_class: type[Event[Any]]
    build_event: Callable[[], Event[Any]]
    partition_key: Callable[[Event[Any]], str]


def _line_status_key(event: Event[Any]) -> str:
    payload = event.payload
    assert isinstance(payload, LineStatusPayload)
    return payload.line_id


def _arrival_key(event: Event[Any]) -> str:
    payload = event.payload
    assert isinstance(payload, ArrivalPayload)
    return payload.station_id


def _disruption_key(event: Event[Any]) -> str:
    payload = event.payload
    assert isinstance(payload, DisruptionPayload)
    return payload.disruption_id


_SMOKE_TOPICS = (
    _SmokeTopic(
        label="line-status",
        table="raw.line_status",
        event_class=LineStatusEvent,
        build_event=_build_line_status_event,
        partition_key=_line_status_key,
    ),
    _SmokeTopic(
        label="arrivals",
        table="raw.arrivals",
        event_class=ArrivalEvent,
        build_event=_build_arrival_event,
        partition_key=_arrival_key,
    ),
    _SmokeTopic(
        label="disruptions",
        table="raw.disruptions",
        event_class=DisruptionEvent,
        build_event=_build_disruption_event,
        partition_key=_disruption_key,
    ),
)


@pytest.mark.parametrize("topic", _SMOKE_TOPICS, ids=[t.label for t in _SMOKE_TOPICS])
async def test_consume_one_event_against_local_stack(topic: _SmokeTopic) -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL is not set")

    event = topic.build_event()
    async with KafkaEventProducer(bootstrap_servers=bootstrap) as producer:
        await producer.publish(
            topic.event_class.TOPIC_NAME,
            event=event,
            key=topic.partition_key(event),
        )

    async with (
        KafkaEventConsumer(
            topic.event_class.TOPIC_NAME,
            bootstrap_servers=bootstrap,
            group_id=f"smoke-{event.event_id}",
        ) as kafka,
        RawEventWriter(dsn, table=topic.table) as writer,
    ):
        consumer = RawEventConsumer[Event[Any]](
            kafka_consumer=kafka,
            writer=writer,
            event_class=topic.event_class,
            topic_label=topic.label,
        )
        await asyncio.wait_for(consumer.run_once(max_messages=1), timeout=10.0)

    select_sql = f"SELECT 1 FROM {topic.table} WHERE event_id = %s"
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(select_sql, (event.event_id,))
        assert cur.fetchone() == (1,)
