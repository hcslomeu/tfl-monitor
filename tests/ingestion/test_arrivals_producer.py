"""Unit tests for :class:`ingestion.producers.ArrivalsProducer`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Self, cast
from uuid import UUID

import httpx
import pytest

from contracts.schemas import ArrivalEvent, ArrivalPayload
from contracts.schemas.tfl_api import TflArrivalPrediction
from ingestion.producers import (
    ARRIVALS_EVENT_TYPE,
    ArrivalsProducer,
    KafkaEventProducer,
    KafkaProducerError,
)
from ingestion.tfl_client import TflClient, arrival_payloads


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
        event: ArrivalEvent,
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


def _tfl_client_failing_per_path(failing_paths: set[str]) -> TflClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in failing_paths:
            return httpx.Response(401)
        return _json_response([])

    return TflClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    )


def _expected_payload_count(fixture: list[dict[str, Any]]) -> int:
    parsed = [TflArrivalPrediction.model_validate(item) for item in fixture]
    return len(arrival_payloads(parsed))


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
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(arrivals_oxford_circus_fixture) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUOXC",),
        )
        published = await producer.run_once()

    expected = _expected_payload_count(arrivals_oxford_circus_fixture)
    assert published == expected
    assert len(kafka.calls) == expected
    assert all(call["topic"] == ArrivalEvent.TOPIC_NAME for call in kafka.calls)
    assert all(call["event"].event_type == ARRIVALS_EVENT_TYPE for call in kafka.calls)
    for call in kafka.calls:
        assert call["key"] == call["event"].payload.station_id


async def test_run_once_uses_injected_clock_and_event_id(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    factory = _fixed_uuid_factory()
    async with _tfl_client_returning(arrivals_oxford_circus_fixture) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUOXC",),
            clock=_fixed_clock,
            event_id_factory=factory,
        )
        await producer.run_once()

    assert kafka.calls, "expected at least one publish"
    for index, call in enumerate(kafka.calls, start=1):
        event = call["event"]
        assert event.ingested_at == _FIXED_TIME
        assert event.event_id == UUID(int=index)


async def test_run_once_handles_tfl_failure_for_one_stop(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _no_sleep)

    # Two stops; first returns 401, second returns the fixture.
    failing_path = "/StopPoint/940GZZLUFAIL/Arrivals"
    success_path = "/StopPoint/940GZZLUOXC/Arrivals"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == failing_path:
            return httpx.Response(401)
        if request.url.path == success_path:
            return _json_response(arrivals_oxford_circus_fixture)
        return httpx.Response(404)

    kafka = _CapturingKafkaProducer()
    async with TflClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    ) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUFAIL", "940GZZLUOXC"),
        )
        published = await producer.run_once()

    expected = _expected_payload_count(arrivals_oxford_circus_fixture)
    assert published == expected
    assert len(kafka.calls) == expected


async def test_run_once_swallows_unexpected_tfl_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _no_sleep)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("network exploded")

    kafka = _CapturingKafkaProducer()
    async with TflClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    ) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUOXC",),
        )
        published = await producer.run_once()

    assert published == 0
    assert kafka.calls == []


async def test_run_once_continues_after_kafka_failure_for_one_arrival(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
) -> None:
    parsed = [TflArrivalPrediction.model_validate(item) for item in arrivals_oxford_circus_fixture]
    payloads: list[ArrivalPayload] = arrival_payloads(parsed)
    assert payloads, "fixture must contain at least one prediction"
    failing_key = payloads[0].station_id

    kafka = _CapturingKafkaProducer()
    kafka.fail_for_keys = {failing_key}

    expected_failures = sum(1 for p in payloads if p.station_id == failing_key)
    expected_published = len(payloads) - expected_failures

    async with _tfl_client_returning(arrivals_oxford_circus_fixture) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUOXC",),
        )
        published = await producer.run_once()

    assert published == expected_published
    assert len(kafka.calls) == expected_published
    assert all(call["key"] != failing_key for call in kafka.calls)


async def test_run_forever_respects_period_and_terminates_on_cancel(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    cycles = {"n": 0}

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        cycles["n"] += 1
        if cycles["n"] >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr("ingestion.producers.arrivals.asyncio.sleep", _fake_sleep)

    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(arrivals_oxford_circus_fixture) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUOXC",),
            period_seconds=30.0,
        )
        with pytest.raises(asyncio.CancelledError):
            await producer.run_forever()

    assert len(sleeps) == 3
    for value in sleeps:
        assert 0.0 <= value <= 30.0


async def test_event_envelope_serialises_to_valid_json(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(arrivals_oxford_circus_fixture) as tfl:
        producer = ArrivalsProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            stops=("940GZZLUOXC",),
        )
        await producer.run_once()

    assert kafka.calls
    captured = kafka.calls[0]["event"]
    encoded = captured.model_dump_json().encode("utf-8")
    roundtrip = ArrivalEvent.model_validate_json(encoded)
    assert roundtrip == captured
    assert isinstance(roundtrip.payload, ArrivalPayload)
    assert roundtrip.event_type == ARRIVALS_EVENT_TYPE


def test_constructor_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError):
        ArrivalsProducer(
            tfl_client=cast(TflClient, object()),
            kafka_producer=cast(KafkaEventProducer, object()),
            period_seconds=0.0,
        )


def test_constructor_rejects_empty_stops() -> None:
    with pytest.raises(ValueError):
        ArrivalsProducer(
            tfl_client=cast(TflClient, object()),
            kafka_producer=cast(KafkaEventProducer, object()),
            stops=(),
        )
