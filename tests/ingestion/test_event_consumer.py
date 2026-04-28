"""Unit tests for :class:`ingestion.consumers.RawEventConsumer`.

Parametrised over the three tier-2 event classes (``LineStatusEvent``,
``ArrivalEvent``, ``DisruptionEvent``) so the loop / failure-isolation
/ lag-tracing contract is exercised once per topic.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self, cast

import psycopg
import pytest
from aiokafka.structs import ConsumerRecord, TopicPartition

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
from tests.ingestion.conftest import make_consumer_record

_NOW = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


def _line_status_event() -> LineStatusEvent:
    payload = LineStatusPayload(
        line_id="victoria",
        line_name="Victoria",
        mode=TransportMode.TUBE,
        status_severity=10,
        status_severity_description="Good Service",
        reason=None,
        valid_from=_NOW,
        valid_to=_NOW + timedelta(days=1),
    )
    return LineStatusEvent(
        event_id=uuid.uuid4(),
        event_type="line-status.snapshot",
        ingested_at=_NOW,
        payload=payload,
    )


def _arrival_event() -> ArrivalEvent:
    payload = ArrivalPayload(
        arrival_id="-1234",
        station_id="940GZZLUOXC",
        station_name="Oxford Circus Underground Station",
        line_id="victoria",
        platform_name="Northbound - Platform 1",
        direction="inbound",
        destination="Walthamstow Central",
        expected_arrival=_NOW + timedelta(seconds=120),
        time_to_station_seconds=120,
        vehicle_id="263",
    )
    return ArrivalEvent(
        event_id=uuid.uuid4(),
        event_type="arrivals.snapshot",
        ingested_at=_NOW,
        payload=payload,
    )


def _disruption_event() -> DisruptionEvent:
    payload = DisruptionPayload(
        disruption_id="abcd1234abcd1234abcd1234abcd1234",
        category=DisruptionCategory.REAL_TIME,
        category_description="RealTime",
        description="Severe delays on the Victoria line.",
        summary="Severe delays on the Victoria line.",
        affected_routes=["victoria"],
        affected_stops=[],
        closure_text="severeDelays",
        severity=6,
        created=_NOW,
        last_update=_NOW,
    )
    return DisruptionEvent(
        event_id=uuid.uuid4(),
        event_type="disruptions.snapshot",
        ingested_at=_NOW,
        payload=payload,
    )


@dataclass(frozen=True)
class _Topic:
    """Bundle the per-topic builders used by parametrised tests."""

    name: str
    label: str
    event_class: type[Event[Any]]
    build_event: Callable[[], Event[Any]]


_TOPICS = (
    _Topic(
        name="line-status",
        label="line-status",
        event_class=LineStatusEvent,
        build_event=_line_status_event,
    ),
    _Topic(
        name="arrivals",
        label="arrivals",
        event_class=ArrivalEvent,
        build_event=_arrival_event,
    ),
    _Topic(
        name="disruptions",
        label="disruptions",
        event_class=DisruptionEvent,
        build_event=_disruption_event,
    ),
)


@pytest.fixture(params=_TOPICS, ids=[t.label for t in _TOPICS])
def topic(request: pytest.FixtureRequest) -> _Topic:
    return cast(_Topic, request.param)


def _record_for(
    topic: _Topic,
    event: Event[Any],
    *,
    partition: int = 0,
    offset: int = 0,
) -> ConsumerRecord[bytes, bytes]:
    return make_consumer_record(
        topic=topic.name,
        value=event.model_dump_json().encode("utf-8"),
        partition=partition,
        offset=offset,
    )


class _FakeKafka:
    """Duck-typed stand-in for :class:`KafkaEventConsumer`."""

    def __init__(self, records: list[ConsumerRecord[bytes, bytes]] | None = None) -> None:
        self._records: list[ConsumerRecord[bytes, bytes]] = list(records or [])
        self.commit_count = 0
        self.seeks: list[tuple[TopicPartition, int]] = []
        self.end_offsets_calls: list[list[TopicPartition]] = []
        self.end_offsets_value: dict[TopicPartition, int] = {}
        self._assignment: set[TopicPartition] = set()
        self.commit_fail_next: BaseException | None = None
        self.seek_fail_next: BaseException | None = None

    def queue(self, record: ConsumerRecord[bytes, bytes]) -> None:
        self._records.append(record)

    def set_end_offsets(self, mapping: dict[TopicPartition, int]) -> None:
        self.end_offsets_value = dict(mapping)
        self._assignment = set(mapping.keys())

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        if self.commit_fail_next is not None:
            exc = self.commit_fail_next
            self.commit_fail_next = None
            raise exc
        self.commit_count += 1

    async def end_offsets(self, partitions: list[TopicPartition]) -> dict[TopicPartition, int]:
        self.end_offsets_calls.append(list(partitions))
        return {tp: self.end_offsets_value.get(tp, 0) for tp in partitions}

    def assignment(self) -> set[TopicPartition]:
        return set(self._assignment)

    def seek(self, partition: TopicPartition, offset: int) -> None:
        if self.seek_fail_next is not None:
            exc = self.seek_fail_next
            self.seek_fail_next = None
            raise exc
        self.seeks.append((partition, offset))

    def __aiter__(self) -> AsyncIterator[ConsumerRecord[bytes, bytes]]:
        records = list(self._records)

        async def _iter() -> AsyncIterator[ConsumerRecord[bytes, bytes]]:
            for record in records:
                yield record

        return _iter()


class _FakeWriter:
    """Duck-typed stand-in for :class:`RawEventWriter`."""

    def __init__(self, *, rowcount: int = 1) -> None:
        self.inserted: list[Event[Any]] = []
        self.reconnect_count = 0
        self._default_rowcount = rowcount
        self.fail_next: BaseException | None = None
        self.reconnect_fail_next: BaseException | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def insert(self, event: Event[Any]) -> int:
        if self.fail_next is not None:
            exc = self.fail_next
            self.fail_next = None
            raise exc
        self.inserted.append(event)
        return self._default_rowcount

    async def reconnect(self) -> None:
        if self.reconnect_fail_next is not None:
            exc = self.reconnect_fail_next
            self.reconnect_fail_next = None
            raise exc
        self.reconnect_count += 1


def _make_consumer(
    topic: _Topic,
    kafka: _FakeKafka,
    writer: _FakeWriter,
    *,
    clock: Callable[[], float] | None = None,
    lag_refresh_messages: int = 50,
    lag_refresh_seconds: float = 30.0,
) -> RawEventConsumer[Event[Any]]:
    return RawEventConsumer[Event[Any]](
        kafka_consumer=cast(KafkaEventConsumer, kafka),
        writer=cast(RawEventWriter, writer),
        event_class=topic.event_class,
        topic_label=topic.label,
        clock=clock or (lambda: 0.0),
        lag_refresh_messages=lag_refresh_messages,
        lag_refresh_seconds=lag_refresh_seconds,
    )


# ---------------------------------------------------------------------------
# Scenarios — parametrised across all three topics
# ---------------------------------------------------------------------------


async def test_run_once_inserts_one_row_per_event(topic: _Topic) -> None:
    events = [topic.build_event() for _ in range(3)]
    kafka = _FakeKafka([_record_for(topic, e, offset=i) for i, e in enumerate(events)])
    writer = _FakeWriter()

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 3
    assert kafka.commit_count == 3
    assert [w.event_id for w in writer.inserted] == [e.event_id for e in events]


async def test_run_once_skips_and_commits_poison_pill(topic: _Topic) -> None:
    bad = make_consumer_record(value=b"{not json", topic=topic.name, offset=0)
    kafka = _FakeKafka([bad])
    writer = _FakeWriter()

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert writer.inserted == []
    assert kafka.commit_count == 1


async def test_run_once_does_not_commit_on_db_operational_error(topic: _Topic) -> None:
    event = topic.build_event()
    kafka = _FakeKafka([_record_for(topic, event, partition=0, offset=7)])
    writer = _FakeWriter()
    writer.fail_next = psycopg.OperationalError("simulated transient db error")

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert writer.inserted == []
    assert kafka.commit_count == 0
    assert writer.reconnect_count == 1
    assert kafka.seeks == [(TopicPartition(topic.name, 0), 7)]


async def test_run_once_does_not_commit_on_unknown_db_error(topic: _Topic) -> None:
    event = topic.build_event()
    kafka = _FakeKafka([_record_for(topic, event, partition=0, offset=3)])
    writer = _FakeWriter()
    writer.fail_next = RuntimeError("boom")

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert writer.inserted == []
    assert kafka.commit_count == 0
    assert writer.reconnect_count == 0
    assert kafka.seeks == [(TopicPartition(topic.name, 0), 3)]


async def test_commit_failure_is_swallowed_and_loop_continues(topic: _Topic) -> None:
    events = [topic.build_event() for _ in range(2)]
    kafka = _FakeKafka([_record_for(topic, e, offset=i) for i, e in enumerate(events)])
    from ingestion.consumers import KafkaConsumerError

    kafka.commit_fail_next = KafkaConsumerError("transient broker hiccup")
    writer = _FakeWriter()

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 2
    assert len(writer.inserted) == 2
    assert kafka.commit_count == 1
    assert kafka.seeks == []


async def test_reconnect_failure_is_swallowed_with_replay_scheduled(
    topic: _Topic,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "ingestion.consumers.event_consumer.asyncio.sleep",
        _no_sleep,
    )

    event = topic.build_event()
    kafka = _FakeKafka([_record_for(topic, event, partition=0, offset=11)])
    writer = _FakeWriter()
    writer.fail_next = psycopg.OperationalError("db down")
    writer.reconnect_fail_next = psycopg.OperationalError("db still down")

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert kafka.commit_count == 0
    assert kafka.seeks == [(TopicPartition(topic.name, 0), 11)]


async def test_reconnect_swallows_non_operational_error(
    topic: _Topic,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "ingestion.consumers.event_consumer.asyncio.sleep",
        _no_sleep,
    )

    event = topic.build_event()
    kafka = _FakeKafka([_record_for(topic, event, partition=0, offset=4)])
    writer = _FakeWriter()
    writer.fail_next = psycopg.OperationalError("db down")
    writer.reconnect_fail_next = TimeoutError("driver hung")

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert kafka.commit_count == 0
    assert kafka.seeks == [(TopicPartition(topic.name, 0), 4)]


async def test_duplicate_returns_zero_rowcount_but_still_commits(topic: _Topic) -> None:
    event = topic.build_event()
    kafka = _FakeKafka([_record_for(topic, event, offset=0)])
    writer = _FakeWriter(rowcount=0)

    consumer = _make_consumer(topic, kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert kafka.commit_count == 1
    assert len(writer.inserted) == 1


async def test_run_forever_refreshes_lag_after_n_messages(topic: _Topic) -> None:
    events = [topic.build_event() for _ in range(60)]
    records = [_record_for(topic, e, offset=i) for i, e in enumerate(events)]
    kafka = _FakeKafka(records)
    tp = TopicPartition(topic.name, 0)
    kafka.set_end_offsets({tp: 100})
    writer = _FakeWriter()

    consumer = _make_consumer(topic, kafka, writer, lag_refresh_messages=50)
    await consumer.run_once()

    assert len(kafka.end_offsets_calls) == 1
    assert kafka.end_offsets_calls[0] == [tp]
    # After processing 50 messages (offsets 0..49), refresh fires.
    # last_seen_offset = 49, end_offset = 100 ⇒ cached lag = 100 - 49 - 1 = 50.
    assert consumer._cached_lag[0] == 50  # noqa: SLF001 - whitebox assertion


async def test_run_forever_refreshes_lag_after_period(topic: _Topic) -> None:
    events = [topic.build_event() for _ in range(5)]
    records = [_record_for(topic, e, offset=i) for i, e in enumerate(events)]
    kafka = _FakeKafka(records)
    tp = TopicPartition(topic.name, 0)
    kafka.set_end_offsets({tp: 10})
    writer = _FakeWriter()

    ticks = iter([0.0, 1.0, 2.0, 3.0, 35.0, 36.0, 37.0])
    consumer = _make_consumer(
        topic,
        kafka,
        writer,
        clock=lambda: next(ticks),
        lag_refresh_messages=1000,
        lag_refresh_seconds=30.0,
    )
    await consumer.run_once()

    assert len(kafka.end_offsets_calls) == 1


def test_constructor_rejects_empty_topic_label() -> None:
    with pytest.raises(ValueError):
        RawEventConsumer[LineStatusEvent](
            kafka_consumer=cast(KafkaEventConsumer, _FakeKafka()),
            writer=cast(RawEventWriter, _FakeWriter()),
            event_class=LineStatusEvent,
            topic_label="",
        )


def test_constructor_rejects_non_positive_lag_refresh_messages() -> None:
    with pytest.raises(ValueError):
        RawEventConsumer[LineStatusEvent](
            kafka_consumer=cast(KafkaEventConsumer, _FakeKafka()),
            writer=cast(RawEventWriter, _FakeWriter()),
            event_class=LineStatusEvent,
            topic_label="line-status",
            lag_refresh_messages=0,
        )


def test_constructor_rejects_non_positive_lag_refresh_seconds() -> None:
    with pytest.raises(ValueError):
        RawEventConsumer[LineStatusEvent](
            kafka_consumer=cast(KafkaEventConsumer, _FakeKafka()),
            writer=cast(RawEventWriter, _FakeWriter()),
            event_class=LineStatusEvent,
            topic_label="line-status",
            lag_refresh_seconds=0.0,
        )
