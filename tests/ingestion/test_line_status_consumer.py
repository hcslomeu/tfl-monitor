"""Unit tests for :class:`ingestion.consumers.LineStatusConsumer`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Self, cast

import psycopg
import pytest
from aiokafka.structs import ConsumerRecord, TopicPartition

from contracts.schemas import LineStatusEvent, LineStatusPayload, TransportMode
from ingestion.consumers import (
    KafkaEventConsumer,
    LineStatusConsumer,
    RawLineStatusWriter,
)
from tests.ingestion.conftest import make_consumer_record


def _build_event(line_id: str = "victoria") -> LineStatusEvent:
    now = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    payload = LineStatusPayload(
        line_id=line_id,
        line_name=line_id.title(),
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


def _record_for(
    event: LineStatusEvent, *, partition: int = 0, offset: int = 0
) -> ConsumerRecord[bytes, bytes]:
    return make_consumer_record(
        value=event.model_dump_json().encode("utf-8"),
        partition=partition,
        offset=offset,
        key=event.payload.line_id.encode("utf-8"),
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
    """Duck-typed stand-in for :class:`RawLineStatusWriter`."""

    def __init__(self, *, rowcount: int = 1) -> None:
        self.inserted: list[LineStatusEvent] = []
        self.reconnect_count = 0
        self._default_rowcount = rowcount
        self.fail_next: BaseException | None = None
        self.reconnect_fail_next: BaseException | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def insert(self, event: LineStatusEvent) -> int:
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
    kafka: _FakeKafka,
    writer: _FakeWriter,
    *,
    clock: Any = None,
    lag_refresh_messages: int = 50,
    lag_refresh_seconds: float = 30.0,
) -> LineStatusConsumer:
    return LineStatusConsumer(
        kafka_consumer=cast(KafkaEventConsumer, kafka),
        writer=cast(RawLineStatusWriter, writer),
        clock=clock or (lambda: 0.0),
        lag_refresh_messages=lag_refresh_messages,
        lag_refresh_seconds=lag_refresh_seconds,
    )


# ---------------------------------------------------------------------------
# Phase 3.6 scenarios
# ---------------------------------------------------------------------------


async def test_run_once_inserts_one_row_per_event() -> None:
    events = [_build_event(line_id=f"line-{i}") for i in range(3)]
    kafka = _FakeKafka([_record_for(e, offset=i) for i, e in enumerate(events)])
    writer = _FakeWriter()

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 3
    assert kafka.commit_count == 3
    assert [w.event_id for w in writer.inserted] == [e.event_id for e in events]


async def test_run_once_skips_and_commits_poison_pill() -> None:
    bad = make_consumer_record(value=b"{not json", offset=0)
    kafka = _FakeKafka([bad])
    writer = _FakeWriter()

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert writer.inserted == []
    assert kafka.commit_count == 1


async def test_run_once_does_not_commit_on_db_operational_error() -> None:
    event = _build_event()
    kafka = _FakeKafka([_record_for(event, partition=0, offset=7)])
    writer = _FakeWriter()
    writer.fail_next = psycopg.OperationalError("simulated transient db error")

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert writer.inserted == []
    assert kafka.commit_count == 0
    assert writer.reconnect_count == 1
    # Without seek aiokafka would silently advance past the failed
    # message; replay is what makes at-least-once correct.
    assert kafka.seeks == [(TopicPartition("line-status", 0), 7)]


async def test_run_once_does_not_commit_on_unknown_db_error() -> None:
    event = _build_event()
    kafka = _FakeKafka([_record_for(event, partition=0, offset=3)])
    writer = _FakeWriter()
    writer.fail_next = RuntimeError("boom")

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert writer.inserted == []
    assert kafka.commit_count == 0
    assert writer.reconnect_count == 0
    assert kafka.seeks == [(TopicPartition("line-status", 0), 3)]


async def test_commit_failure_is_swallowed_and_loop_continues() -> None:
    events = [_build_event(line_id=f"line-{i}") for i in range(2)]
    kafka = _FakeKafka([_record_for(e, offset=i) for i, e in enumerate(events)])
    # First commit blows up; second must still be attempted (loop survives).
    from ingestion.consumers import KafkaConsumerError

    kafka.commit_fail_next = KafkaConsumerError("transient broker hiccup")
    writer = _FakeWriter()

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    # Both inserts ran; one commit succeeded after the first was swallowed.
    assert inserted == 2
    assert len(writer.inserted) == 2
    assert kafka.commit_count == 1
    assert kafka.seeks == []  # commit failure must NOT trigger a replay


async def test_reconnect_failure_is_swallowed_with_replay_scheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "ingestion.consumers.line_status.asyncio.sleep",
        _no_sleep,
    )

    event = _build_event()
    kafka = _FakeKafka([_record_for(event, partition=0, offset=11)])
    writer = _FakeWriter()
    writer.fail_next = psycopg.OperationalError("db down")
    writer.reconnect_fail_next = psycopg.OperationalError("db still down")

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    # Daemon stays alive even when reconnect itself raises; the message
    # is queued for replay so no row goes missing once the DB is back.
    assert inserted == 0
    assert kafka.commit_count == 0
    assert kafka.seeks == [(TopicPartition("line-status", 0), 11)]


async def test_reconnect_swallows_non_operational_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "ingestion.consumers.line_status.asyncio.sleep",
        _no_sleep,
    )

    event = _build_event()
    kafka = _FakeKafka([_record_for(event, partition=0, offset=4)])
    writer = _FakeWriter()
    writer.fail_next = psycopg.OperationalError("db down")
    # Driver-level glitch unrelated to OperationalError must not bubble
    # out of _safe_reconnect; otherwise _schedule_replay never runs.
    writer.reconnect_fail_next = TimeoutError("driver hung")

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    assert inserted == 0
    assert kafka.commit_count == 0
    assert kafka.seeks == [(TopicPartition("line-status", 0), 4)]


async def test_duplicate_returns_zero_rowcount_but_still_commits() -> None:
    event = _build_event()
    kafka = _FakeKafka([_record_for(event, offset=0)])
    writer = _FakeWriter(rowcount=0)

    consumer = _make_consumer(kafka, writer)
    inserted = await consumer.run_once()

    # Duplicate row → rowcount 0 → not counted as "inserted", but the
    # message *was* processed so the offset must be committed.
    assert inserted == 0
    assert kafka.commit_count == 1
    assert len(writer.inserted) == 1


async def test_run_forever_refreshes_lag_after_n_messages() -> None:
    events = [_build_event() for _ in range(60)]
    records = [_record_for(e, offset=i) for i, e in enumerate(events)]
    kafka = _FakeKafka(records)
    tp = TopicPartition("line-status", 0)
    kafka.set_end_offsets({tp: 100})
    writer = _FakeWriter()

    consumer = _make_consumer(kafka, writer, lag_refresh_messages=50)
    await consumer.run_once()

    assert len(kafka.end_offsets_calls) == 1
    assert kafka.end_offsets_calls[0] == [tp]
    # After processing 50 messages (offsets 0..49), refresh fires.
    # last_seen_offset = 49, end_offset = 100 ⇒ cached lag = 100 - 49 - 1 = 50.
    assert consumer._cached_lag[0] == 50  # noqa: SLF001 - whitebox assertion


async def test_run_forever_refreshes_lag_after_period() -> None:
    events = [_build_event() for _ in range(5)]
    records = [_record_for(e, offset=i) for i, e in enumerate(events)]
    kafka = _FakeKafka(records)
    tp = TopicPartition("line-status", 0)
    kafka.set_end_offsets({tp: 10})
    writer = _FakeWriter()

    ticks = iter([0.0, 1.0, 2.0, 3.0, 35.0, 36.0, 37.0])
    consumer = _make_consumer(
        kafka,
        writer,
        clock=lambda: next(ticks),
        lag_refresh_messages=1000,
        lag_refresh_seconds=30.0,
    )
    await consumer.run_once()

    # Time-based refresh should fire exactly once when 35 s elapsed
    # crosses the 30 s threshold (between message 3 and 4).
    assert len(kafka.end_offsets_calls) == 1
