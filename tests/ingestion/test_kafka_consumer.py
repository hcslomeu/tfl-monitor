"""Unit tests for :class:`ingestion.consumers.KafkaEventConsumer`."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from aiokafka.structs import TopicPartition

from ingestion.consumers import KafkaConsumerError, KafkaEventConsumer
from tests.ingestion.conftest import FakeAIOKafkaConsumer, make_consumer_record


def _factory_returning(fake: FakeAIOKafkaConsumer) -> Any:
    def _factory(*args: Any, **kwargs: Any) -> AIOKafkaConsumer:
        fake.args = args
        fake.kwargs.update(kwargs)
        return cast(AIOKafkaConsumer, fake)

    return _factory


async def test_aenter_starts_and_aexit_stops_consumer() -> None:
    fake = FakeAIOKafkaConsumer()

    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    ):
        assert fake.started is True
        assert fake.stopped is False

    assert fake.stopped is True


async def test_aiter_delegates_to_underlying_consumer() -> None:
    fake = FakeAIOKafkaConsumer()
    fake.queue(make_consumer_record(value=b"a", offset=0))
    fake.queue(make_consumer_record(value=b"b", offset=1))
    fake.queue(make_consumer_record(value=b"c", offset=2))

    seen: list[bytes | None] = []
    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    ) as consumer:
        async for record in consumer:
            seen.append(record.value)

    assert seen == [b"a", b"b", b"c"]


async def test_commit_translates_kafka_error_to_kafka_consumer_error() -> None:
    fake = FakeAIOKafkaConsumer()
    fake.commit_fail_next = KafkaError("simulated commit failure")

    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    ) as consumer:
        with pytest.raises(KafkaConsumerError):
            await consumer.commit()


async def test_end_offsets_translates_kafka_error_to_kafka_consumer_error() -> None:
    fake = FakeAIOKafkaConsumer()
    fake.end_offsets_fail_next = KafkaError("simulated end_offsets failure")

    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    ) as consumer:
        with pytest.raises(KafkaConsumerError):
            await consumer.end_offsets([TopicPartition("line-status", 0)])


async def test_constructor_passes_group_id_and_auto_offset_reset_to_factory() -> None:
    fake = FakeAIOKafkaConsumer()
    captured: dict[str, Any] = {}
    captured_args: list[Any] = []

    def _factory(*args: Any, **kwargs: Any) -> AIOKafkaConsumer:
        captured_args.extend(args)
        captured.update(kwargs)
        return cast(AIOKafkaConsumer, fake)

    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="tfl-monitor-line-status-writer",
        auto_offset_reset="latest",
        consumer_factory=_factory,
    ):
        pass

    assert captured_args == ["line-status"]
    assert captured["bootstrap_servers"] == "localhost:19092"
    assert captured["group_id"] == "tfl-monitor-line-status-writer"
    assert captured["auto_offset_reset"] == "latest"
    assert captured["enable_auto_commit"] is False


def test_constructor_rejects_empty_topic() -> None:
    with pytest.raises(ValueError):
        KafkaEventConsumer("", bootstrap_servers="localhost:19092", group_id="g")


def test_constructor_rejects_empty_bootstrap_servers() -> None:
    with pytest.raises(ValueError):
        KafkaEventConsumer("line-status", bootstrap_servers="", group_id="g")


def test_constructor_rejects_empty_group_id() -> None:
    with pytest.raises(ValueError):
        KafkaEventConsumer(
            "line-status",
            bootstrap_servers="localhost:19092",
            group_id="",
        )


async def test_commit_outside_context_manager_fails() -> None:
    consumer = KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(FakeAIOKafkaConsumer()),
    )
    with pytest.raises(KafkaConsumerError):
        await consumer.commit()


async def test_aenter_cleans_up_on_start_failure() -> None:
    fake = FakeAIOKafkaConsumer()
    fake.start_fail = KafkaError("simulated start failure")

    consumer = KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    )
    with pytest.raises(KafkaConsumerError):
        await consumer.__aenter__()

    # Partial consumer was stopped and the wrapper reset so a retry
    # cannot accidentally use a half-initialized client.
    assert fake.stopped is True
    with pytest.raises(KafkaConsumerError):
        await consumer.commit()


async def test_seek_translates_kafka_error_to_kafka_consumer_error() -> None:
    fake = FakeAIOKafkaConsumer()
    fake.seek_fail_next = KafkaError("simulated seek failure")

    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    ) as consumer:
        with pytest.raises(KafkaConsumerError):
            consumer.seek(TopicPartition("line-status", 0), 42)


async def test_seek_records_partition_and_offset() -> None:
    fake = FakeAIOKafkaConsumer()
    tp = TopicPartition("line-status", 0)

    async with KafkaEventConsumer(
        "line-status",
        bootstrap_servers="localhost:19092",
        group_id="g",
        consumer_factory=_factory_returning(fake),
    ) as consumer:
        consumer.seek(tp, 42)

    assert fake.seeks == [(tp, 42)]
