"""Behavioural tests for :class:`ingestion.tfl_client.TflClient`."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflDisruption,
    TflLineResponse,
)
from ingestion.tfl_client import TflClient, TflClientError


def _json_response(payload: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client(transport: httpx.MockTransport, **kwargs: Any) -> TflClient:
    return TflClient(app_key="test-key", transport=transport, **kwargs)


async def test_fetch_line_statuses_returns_tier1_models(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(line_status_tube_fixture)

    async with _client(make_transport(handler)) as client:
        result = await client.fetch_line_statuses(["tube"])

    assert captured[0].url.path == "/Line/Mode/tube/Status"
    assert all(isinstance(item, TflLineResponse) for item in result)
    assert len(result) == len(line_status_tube_fixture)


async def test_fetch_arrivals_returns_tier1_models(
    arrivals_oxford_circus_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(arrivals_oxford_circus_fixture)

    async with _client(make_transport(handler)) as client:
        result = await client.fetch_arrivals("940GZZLUOXC")

    assert captured[0].url.path == "/StopPoint/940GZZLUOXC/Arrivals"
    assert all(isinstance(item, TflArrivalPrediction) for item in result)
    assert len(result) == len(arrivals_oxford_circus_fixture)


async def test_fetch_disruptions_returns_tier1_models(
    disruptions_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(disruptions_tube_fixture)

    async with _client(make_transport(handler)) as client:
        result = await client.fetch_disruptions(["tube"])

    assert captured[0].url.path == "/Line/Mode/tube/Disruption"
    assert all(isinstance(item, TflDisruption) for item in result)
    assert len(result) == len(disruptions_tube_fixture)


async def test_app_key_in_query_params(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _json_response(line_status_tube_fixture)

    async with _client(make_transport(handler)) as client:
        await client.fetch_line_statuses(["tube"])

    assert captured, "no requests captured"
    assert captured[0].url.params.get("app_key") == "test-key"


async def test_app_key_not_logged_via_logfire(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_spans: list[dict[str, Any]] = []

    class _DummySpan:
        def __init__(self, attributes: dict[str, Any]) -> None:
            captured_spans.append(attributes)

        def __enter__(self) -> _DummySpan:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _fake_span(_name: str, **attributes: Any) -> _DummySpan:
        return _DummySpan(attributes)

    import ingestion.tfl_client.client as client_module

    monkeypatch.setattr(client_module.logfire, "span", _fake_span)

    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(line_status_tube_fixture)

    async with _client(make_transport(handler)) as client:
        await client.fetch_line_statuses(["tube"])

    assert captured_spans, "logfire span not invoked"
    params = captured_spans[0].get("params", {})
    assert params.get("app_key") == "***"
    assert "test-key" not in json.dumps(captured_spans, default=str)


async def test_request_does_not_mutate_caller_params(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(line_status_tube_fixture)

    caller_params: dict[str, Any] = {"foo": "bar"}
    async with _client(make_transport(handler)) as client:
        await client._request("/Line/Mode/tube/Status", params=caller_params)

    assert caller_params == {"foo": "bar"}, (
        "TflClient._request must not mutate the caller's params dict"
    )


async def test_429_respects_retry_after(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
    script_responses: Callable[[list[httpx.Response]], Callable[[httpx.Request], httpx.Response]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _fake_sleep)

    handler = script_responses(
        [
            httpx.Response(429, headers={"Retry-After": "1"}),
            _json_response(line_status_tube_fixture),
        ]
    )
    async with _client(make_transport(handler), max_attempts=2) as client:
        result = await client.fetch_line_statuses(["tube"])

    assert len(result) == len(line_status_tube_fixture)
    assert sleeps == [1.0]


async def test_429_falls_back_to_backoff_on_unparseable_retry_after(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
    script_responses: Callable[[list[httpx.Response]], Callable[[httpx.Request], httpx.Response]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _fake_sleep)

    handler = script_responses(
        [
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            _json_response(line_status_tube_fixture),
        ]
    )
    async with _client(make_transport(handler), max_attempts=2) as client:
        result = await client.fetch_line_statuses(["tube"])

    assert len(result) == len(line_status_tube_fixture)
    assert sleeps == [0.5]


async def test_500_retries_then_succeeds(
    line_status_tube_fixture: list[dict[str, Any]],
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
    script_responses: Callable[[list[httpx.Response]], Callable[[httpx.Request], httpx.Response]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _fake_sleep)

    handler = script_responses(
        [
            httpx.Response(500),
            httpx.Response(500),
            _json_response(line_status_tube_fixture),
        ]
    )
    async with _client(make_transport(handler), max_attempts=3) as client:
        result = await client.fetch_line_statuses(["tube"])

    assert len(result) == len(line_status_tube_fixture)
    assert sleeps == [0.5, 1.0]


async def test_401_raised_immediately(
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
) -> None:
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401)

    async with _client(make_transport(handler), max_attempts=3) as client:
        with pytest.raises(TflClientError):
            await client.fetch_line_statuses(["tube"])

    assert len(attempts) == 1


async def test_timeout_retries_then_gives_up(
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    async def _fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("simulated timeout", request=request)

    async with _client(make_transport(handler), max_attempts=3) as client:
        with pytest.raises(TflClientError):
            await client.fetch_line_statuses(["tube"])

    assert len(attempts) == 3


async def test_transport_error_retries_then_gives_up(
    make_transport: Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    async def _fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("ingestion.tfl_client.retry.asyncio.sleep", _fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("simulated connect error", request=request)

    async with _client(make_transport(handler), max_attempts=2) as client:
        with pytest.raises(TflClientError):
            await client.fetch_line_statuses(["tube"])

    assert len(attempts) == 2


def test_constructor_rejects_empty_app_key() -> None:
    with pytest.raises(TflClientError):
        TflClient(app_key="")


def test_from_env_requires_app_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TFL_APP_KEY", raising=False)
    with pytest.raises(TflClientError):
        TflClient.from_env()


def test_from_env_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TFL_APP_KEY", "env-key")
    client = TflClient.from_env()
    assert client._app_key == "env-key"


async def test_request_outside_context_manager_fails() -> None:
    client = TflClient(app_key="test-key")
    with pytest.raises(TflClientError):
        await client.fetch_line_statuses(["tube"])


def test_modes_must_be_non_empty() -> None:
    client = TflClient(app_key="test-key")
    with pytest.raises(TflClientError):
        client._join_modes([])
    with pytest.raises(TflClientError):
        client._join_modes([""])
