"""Unit tests for :class:`ingestion.producers.DisruptionsProducer`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Self, cast
from uuid import UUID

import httpx
import pytest

from contracts.schemas import DisruptionEvent, DisruptionPayload
from contracts.schemas.tfl_api import TflDisruption
from ingestion.producers import (
    DISRUPTIONS_EVENT_TYPE,
    DisruptionsProducer,
    KafkaEventProducer,
    KafkaProducerError,
)
from ingestion.tfl_client import TflClient, disruption_payloads


class _CapturingKafkaProducer:
    """Captures every ``publish`` call for assertion in tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_for_keys: set[str] = set()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def publish(
        self,
        topic: str,
        *,
        event: DisruptionEvent,
        key: str | None,
    ) -> None:
        if key is not None and key in self.fail_for_keys:
            raise KafkaProducerError(f"simulated kafka failure for key={key!r}")
        self.calls.append({"topic": topic, "event": event, "key": key})


def _json_response(payload: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _tfl_client_returning(payload: list[dict[str, Any]]) -> TflClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(payload)

    return TflClient(app_key="test-key", transport=httpx.MockTransport(handler))


def _tfl_client_failing() -> TflClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    return TflClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    )


def _expected_payloads(fixture: list[dict[str, Any]]) -> list[DisruptionPayload]:
    parsed = [TflDisruption.model_validate(item) for item in fixture]
    return disruption_payloads(parsed)


_FIXED_TIME = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


def _fixed_uuid_factory() -> Callable[[], UUID]:
    counter = {"n": 0}

    def _next() -> UUID:
        counter["n"] += 1
        return UUID(int=counter["n"])

    return _next


def _fixed_clock() -> datetime:
    return _FIXED_TIME


async def test_run_once_publishes_one_event_per_payload(
    disruptions_tube_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(disruptions_tube_fixture) as tfl:
        producer = DisruptionsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
        )
        published = await producer.run_once()

    expected = _expected_payloads(disruptions_tube_fixture)
    assert published == len(expected)
    assert len(kafka.calls) == len(expected)
    assert all(call["topic"] == DisruptionEvent.TOPIC_NAME for call in kafka.calls)
    assert all(call["event"].event_type == DISRUPTIONS_EVENT_TYPE for call in kafka.calls)
    for call in kafka.calls:
        assert call["key"] == call["event"].payload.disruption_id


async def test_run_once_uses_injected_clock_and_event_id(
    disruptions_tube_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    factory = _fixed_uuid_factory()
    async with _tfl_client_returning(disruptions_tube_fixture) as tfl:
        producer = DisruptionsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
            clock=_fixed_clock,
            event_id_factory=factory,
        )
        await producer.run_once()

    assert kafka.calls, "expected at least one publish"
    for index, call in enumerate(kafka.calls, start=1):
        event = call["event"]
        assert event.ingested_at == _FIXED_TIME
        assert event.event_id == UUID(int=index)


async def test_run_once_handles_tfl_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _no_sleep)

    kafka = _CapturingKafkaProducer()
    async with _tfl_client_failing() as tfl:
        producer = DisruptionsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
        )
        published = await producer.run_once()

    assert published == 0
    assert kafka.calls == []


async def test_run_once_continues_after_kafka_failure_for_one_disruption(
    disruptions_tube_fixture: list[dict[str, Any]],
) -> None:
    payloads = _expected_payloads(disruptions_tube_fixture)
    assert payloads, "fixture must contain at least one disruption"
    failing_key = payloads[0].disruption_id

    kafka = _CapturingKafkaProducer()
    kafka.fail_for_keys = {failing_key}

    expected_failures = sum(1 for p in payloads if p.disruption_id == failing_key)
    expected_published = len(payloads) - expected_failures

    async with _tfl_client_returning(disruptions_tube_fixture) as tfl:
        producer = DisruptionsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
        )
        published = await producer.run_once()

    assert published == expected_published
    assert len(kafka.calls) == expected_published
    assert all(call["key"] != failing_key for call in kafka.calls)


async def test_run_forever_respects_period_and_terminates_on_cancel(
    disruptions_tube_fixture: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    cycles = {"n": 0}

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        cycles["n"] += 1
        if cycles["n"] >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr("ingestion.producers.disruptions.asyncio.sleep", _fake_sleep)

    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(disruptions_tube_fixture) as tfl:
        producer = DisruptionsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
            period_seconds=300.0,
        )
        with pytest.raises(asyncio.CancelledError):
            await producer.run_forever()

    assert len(sleeps) == 3
    for value in sleeps:
        assert 0.0 <= value <= 300.0


async def test_event_envelope_serialises_to_valid_json(
    disruptions_tube_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(disruptions_tube_fixture) as tfl:
        producer = DisruptionsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
        )
        await producer.run_once()

    assert kafka.calls
    captured = kafka.calls[0]["event"]
    encoded = captured.model_dump_json().encode("utf-8")
    roundtrip = DisruptionEvent.model_validate_json(encoded)
    assert roundtrip == captured
    assert isinstance(roundtrip.payload, DisruptionPayload)
    assert roundtrip.event_type == DISRUPTIONS_EVENT_TYPE


def test_constructor_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError):
        DisruptionsProducer(
            tfl_client=cast(TflClient, object()),
            kafka_producer=cast(KafkaEventProducer, object()),
            period_seconds=0.0,
        )


def test_constructor_rejects_empty_modes() -> None:
    with pytest.raises(ValueError):
        DisruptionsProducer(
            tfl_client=cast(TflClient, object()),
            kafka_producer=cast(KafkaEventProducer, object()),
            modes=(),
        )
