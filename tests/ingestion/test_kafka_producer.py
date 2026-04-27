"""Unit tests for :class:`ingestion.producers.KafkaEventProducer`."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from pydantic import BaseModel

from ingestion.producers import KafkaEventProducer, KafkaProducerError


class _Sample(BaseModel):
    """Tiny model used to stand in for ``LineStatusEvent`` in unit tests."""

    line_id: str
    severity: int


class _FakeAIOKafkaProducer:
    """In-memory stand-in for ``AIOKafkaProducer`` used by unit tests."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs: dict[str, Any] = dict(kwargs)
        self.started = False
        self.stopped = False
        self.sent: list[dict[str, Any]] = []
        self.fail_next: BaseException | None = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(
        self,
        topic: str,
        value: bytes | None = None,
        key: bytes | None = None,
    ) -> None:
        if self.fail_next is not None:
            raise self.fail_next
        self.sent.append({"topic": topic, "value": value, "key": key})


def _factory_returning(fake: _FakeAIOKafkaProducer) -> Any:
    def _factory(**kwargs: Any) -> AIOKafkaProducer:
        fake.kwargs.update(kwargs)
        return cast(AIOKafkaProducer, fake)

    return _factory


async def test_publish_serialises_event_via_pydantic_json() -> None:
    fake = _FakeAIOKafkaProducer()
    sample = _Sample(line_id="victoria", severity=10)

    async with KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(fake),
    ) as producer:
        await producer.publish("line-status", event=sample, key="victoria")

    assert fake.sent == [
        {
            "topic": "line-status",
            "value": sample.model_dump_json().encode("utf-8"),
            "key": b"victoria",
        }
    ]


async def test_publish_passes_key_as_utf8_bytes() -> None:
    fake = _FakeAIOKafkaProducer()
    sample = _Sample(line_id="elizabeth-line", severity=10)

    async with KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(fake),
    ) as producer:
        await producer.publish("line-status", event=sample, key="elizabeth-line")

    assert fake.sent[0]["key"] == b"elizabeth-line"


async def test_publish_omits_key_when_none() -> None:
    fake = _FakeAIOKafkaProducer()
    sample = _Sample(line_id="dlr", severity=10)

    async with KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(fake),
    ) as producer:
        await producer.publish("line-status", event=sample, key=None)

    assert fake.sent[0]["key"] is None


async def test_publish_translates_kafka_error_to_kafka_producer_error() -> None:
    fake = _FakeAIOKafkaProducer()
    fake.fail_next = KafkaError("simulated broker error")
    sample = _Sample(line_id="overground", severity=10)

    async with KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(fake),
    ) as producer:
        with pytest.raises(KafkaProducerError):
            await producer.publish("line-status", event=sample, key="overground")


async def test_aenter_starts_and_aexit_stops_producer() -> None:
    fake = _FakeAIOKafkaProducer()

    class _Tracker:
        def __init__(self) -> None:
            self.entered = False
            self.exited = False

    tracker = _Tracker()

    async with KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(fake),
    ) as _:
        tracker.entered = True
        assert fake.started is True
        assert fake.stopped is False

    tracker.exited = True
    assert fake.stopped is True
    assert tracker.entered and tracker.exited


def test_constructor_rejects_empty_bootstrap_servers() -> None:
    with pytest.raises(KafkaProducerError):
        KafkaEventProducer(bootstrap_servers="")


async def test_publish_outside_context_manager_fails() -> None:
    producer = KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(_FakeAIOKafkaProducer()),
    )
    sample = _Sample(line_id="bus", severity=10)
    with pytest.raises(KafkaProducerError):
        await producer.publish("line-status", event=sample, key="bus")


async def test_producer_factory_receives_expected_kwargs() -> None:
    fake = _FakeAIOKafkaProducer()
    captured: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> AIOKafkaProducer:
        captured.update(kwargs)
        return cast(AIOKafkaProducer, fake)

    async with KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        client_id="test-client",
        producer_factory=_factory,
    ) as _:
        pass

    assert captured["bootstrap_servers"] == "localhost:19092"
    assert captured["client_id"] == "test-client"
    assert captured["enable_idempotence"] is True
    assert captured["acks"] == "all"
    assert "linger_ms" in captured


async def test_kafka_event_producer_isinstance_of_self_returns_self() -> None:
    fake = _FakeAIOKafkaProducer()
    producer = KafkaEventProducer(
        bootstrap_servers="localhost:19092",
        producer_factory=_factory_returning(fake),
    )
    async with producer as bound:
        assert isinstance(bound, KafkaEventProducer)
        assert bound is producer
