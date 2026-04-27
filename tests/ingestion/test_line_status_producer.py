"""Unit tests for :class:`ingestion.producers.LineStatusProducer`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Self, cast
from uuid import UUID

import httpx
import pytest

from contracts.schemas import LineStatusEvent, LineStatusPayload
from contracts.schemas.tfl_api import TflLineResponse
from ingestion.producers import (
    LINE_STATUS_EVENT_TYPE,
    KafkaEventProducer,
    KafkaProducerError,
    LineStatusProducer,
)
from ingestion.tfl_client import TflClient, line_status_payloads


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
        event: LineStatusEvent,
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


def _expected_payload_count(fixture: list[dict[str, Any]]) -> int:
    parsed = [TflLineResponse.model_validate(item) for item in fixture]
    return len(line_status_payloads(parsed))


def _expected_failures_for_keys(
    fixture: list[dict[str, Any]],
    keys: set[str],
) -> int:
    parsed = [TflLineResponse.model_validate(item) for item in fixture]
    return sum(1 for payload in line_status_payloads(parsed) if payload.line_id in keys)


_FIXED_TIME = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)


def _fixed_uuid_factory() -> Callable[[], UUID]:
    counter = {"n": 0}

    def _next() -> UUID:
        counter["n"] += 1
        return UUID(int=counter["n"])

    return _next


def _fixed_clock() -> datetime:
    return _FIXED_TIME


async def test_run_once_publishes_one_event_per_payload(
    line_status_multi_mode_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(line_status_multi_mode_fixture) as tfl:
        producer = LineStatusProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
        )
        published = await producer.run_once()

    expected = _expected_payload_count(line_status_multi_mode_fixture)
    assert published == expected
    assert len(kafka.calls) == expected
    assert all(call["topic"] == LineStatusEvent.TOPIC_NAME for call in kafka.calls)
    assert all(call["event"].event_type == LINE_STATUS_EVENT_TYPE for call in kafka.calls)
    for call in kafka.calls:
        assert call["key"] == call["event"].payload.line_id


async def test_run_once_uses_injected_clock_and_event_id(
    line_status_tube_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    factory = _fixed_uuid_factory()
    async with _tfl_client_returning(line_status_tube_fixture) as tfl:
        producer = LineStatusProducer(
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
        producer = LineStatusProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
        )
        published = await producer.run_once()

    assert published == 0
    assert kafka.calls == []


async def test_run_once_continues_after_kafka_failure_for_one_line(
    line_status_multi_mode_fixture: list[dict[str, Any]],
) -> None:
    failing_keys = {"victoria"}
    expected_failures = _expected_failures_for_keys(line_status_multi_mode_fixture, failing_keys)
    assert expected_failures > 0, "fixture must include at least one victoria payload"

    expected_total = _expected_payload_count(line_status_multi_mode_fixture)
    expected_published = expected_total - expected_failures

    kafka = _CapturingKafkaProducer()
    kafka.fail_for_keys = failing_keys

    async with _tfl_client_returning(line_status_multi_mode_fixture) as tfl:
        producer = LineStatusProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
        )
        published = await producer.run_once()

    assert published == expected_published
    assert len(kafka.calls) == expected_published
    assert all(call["key"] not in failing_keys for call in kafka.calls)


async def test_run_forever_respects_period_and_terminates_on_cancel(
    line_status_tube_fixture: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    cycles = {"n": 0}

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        cycles["n"] += 1
        if cycles["n"] >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr("ingestion.producers.line_status.asyncio.sleep", _fake_sleep)

    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(line_status_tube_fixture) as tfl:
        producer = LineStatusProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
            period_seconds=30.0,
        )
        with pytest.raises(asyncio.CancelledError):
            await producer.run_forever()

    assert len(sleeps) == 3
    for value in sleeps:
        assert 0.0 <= value <= 30.0


async def test_event_envelope_serialises_to_valid_json(
    line_status_tube_fixture: list[dict[str, Any]],
) -> None:
    kafka = _CapturingKafkaProducer()
    async with _tfl_client_returning(line_status_tube_fixture) as tfl:
        producer = LineStatusProducer(
            tfl_client=tfl,
            kafka_producer=cast(KafkaEventProducer, kafka),
            modes=("tube",),
        )
        await producer.run_once()

    assert kafka.calls
    captured = kafka.calls[0]["event"]
    encoded = captured.model_dump_json().encode("utf-8")
    roundtrip = LineStatusEvent.model_validate_json(encoded)
    assert roundtrip == captured
    assert isinstance(roundtrip.payload, LineStatusPayload)
    assert roundtrip.event_type == LINE_STATUS_EVENT_TYPE


def test_constructor_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError):
        LineStatusProducer(
            tfl_client=cast(TflClient, object()),
            kafka_producer=cast(KafkaEventProducer, object()),
            period_seconds=0.0,
        )
