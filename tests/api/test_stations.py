"""Unit tests for the hybrid NaPTAN ↔ station-name resolver."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from api import stations
from contracts.schemas.tfl_api import TflStopPoint
from ingestion.tfl_client.client import TflClientError


@dataclass
class FakeTflClient:
    """Minimal stand-in for ``TflClient`` covering ``fetch_stop_point``."""

    responses: dict[str, str]
    fail_for: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    async def fetch_stop_point(self, naptan_id: str) -> TflStopPoint:
        self.calls.append(naptan_id)
        if naptan_id in self.fail_for:
            raise RuntimeError(f"upstream TfL failure for {naptan_id}")
        if naptan_id not in self.responses:
            raise RuntimeError(f"unknown naptan {naptan_id}")
        return TflStopPoint(naptan_id=naptan_id, common_name=self.responses[naptan_id])


@pytest.mark.asyncio
async def test_empty_input_returns_empty_dict(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory()

    assert await stations.resolve_naptans(pool=pool, tfl_client=None, naptan_ids=[]) == {}


@pytest.mark.asyncio
async def test_fast_path_resolves_via_dim_stations(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory(
        [
            {"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"},
            {"naptan_id": "940GZZLUHBN", "name": "Holborn"},
        ]
    )

    result = await stations.resolve_naptans(
        pool=pool,
        tfl_client=None,
        naptan_ids=["940GZZLUOXC", "940GZZLUHBN"],
    )

    assert result == {"940GZZLUOXC": "Oxford Circus", "940GZZLUHBN": "Holborn"}


@pytest.mark.asyncio
async def test_misses_become_none_when_no_fallback(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory(
        [{"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"}],
    )

    result = await stations.resolve_naptans(
        pool=pool,
        tfl_client=None,
        naptan_ids=["940GZZLUOXC", "490UNKNOWN"],
    )

    assert result == {"940GZZLUOXC": "Oxford Circus", "490UNKNOWN": None}


@pytest.mark.asyncio
async def test_fallback_calls_tfl_client_on_miss(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory([])
    fake_client = FakeTflClient(responses={"490UNKNOWN": "Mystery Bus Stop"})

    result = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["490UNKNOWN"],
    )

    assert result == {"490UNKNOWN": "Mystery Bus Stop"}
    assert fake_client.calls == ["490UNKNOWN"]


@pytest.mark.asyncio
async def test_fallback_failure_returns_none(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory([])
    fake_client = FakeTflClient(responses={}, fail_for={"940GBOGUS"})

    result = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["940GBOGUS"],
    )

    assert result == {"940GBOGUS": None}
    assert fake_client.calls == ["940GBOGUS"]


@pytest.mark.asyncio
async def test_resolved_names_are_cached_across_calls(
    fake_pool_factory: Callable[..., Any],
) -> None:
    pool = fake_pool_factory(
        [{"naptan_id": "940GZZLUOXC", "name": "Oxford Circus"}],
        [],  # second call's seed batch should not be touched
    )

    first = await stations.resolve_naptans(
        pool=pool,
        tfl_client=None,
        naptan_ids=["940GZZLUOXC"],
    )
    second = await stations.resolve_naptans(
        pool=pool,
        tfl_client=None,
        naptan_ids=["940GZZLUOXC"],
    )

    assert first == {"940GZZLUOXC": "Oxford Circus"}
    assert second == {"940GZZLUOXC": "Oxford Circus"}
    # Only the first call drained a batch; the cached lookup short-circuits.
    assert len(pool.conn.batches) == 1


@pytest.mark.asyncio
async def test_misses_are_cached_only_when_fallback_is_wired(
    fake_pool_factory: Callable[..., Any],
) -> None:
    """A confirmed miss caches as ``None`` only when the TfL fallback was
    attempted — otherwise a later call with a wired client should retry."""
    pool = fake_pool_factory([], [])  # two empty seed batches
    fake_client = FakeTflClient(responses={"490NEW": "New Stop"})

    no_fallback = await stations.resolve_naptans(
        pool=pool,
        tfl_client=None,
        naptan_ids=["490NEW"],
    )
    with_fallback = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["490NEW"],
    )

    assert no_fallback == {"490NEW": None}
    assert with_fallback == {"490NEW": "New Stop"}
    assert fake_client.calls == ["490NEW"]


@pytest.mark.asyncio
async def test_transient_failures_are_not_cached(
    fake_pool_factory: Callable[..., Any],
) -> None:
    """A 5xx / timeout / network error must not poison the cache — the
    next request should retry the lookup rather than surfacing ``None``
    permanently after a single hiccup."""

    @dataclass
    class FlakyClient:
        recovered_name: str = "Recovered Station"
        calls: list[str] = field(default_factory=list)

        async def fetch_stop_point(self, naptan_id: str) -> TflStopPoint:
            self.calls.append(naptan_id)
            if len(self.calls) == 1:
                fake_request = httpx.Request("GET", f"/StopPoint/{naptan_id}")
                fake_response = httpx.Response(503, request=fake_request)
                http_exc = httpx.HTTPStatusError(
                    "Service Unavailable", request=fake_request, response=fake_response
                )
                raise TflClientError("TfL request failed: HTTP 503") from http_exc
            return TflStopPoint(naptan_id=naptan_id, common_name=self.recovered_name)

    pool = fake_pool_factory([], [])  # two empty seed batches → both calls miss
    fake_client = FlakyClient()

    first = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["490FLAKY"],
    )
    second = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["490FLAKY"],
    )

    assert first == {"490FLAKY": None}
    assert second == {"490FLAKY": "Recovered Station"}
    assert fake_client.calls == ["490FLAKY", "490FLAKY"]


@pytest.mark.asyncio
async def test_definitive_404_is_cached(
    fake_pool_factory: Callable[..., Any],
) -> None:
    """A 404 confirms the NaPTAN does not exist — cache the miss so the
    next request short-circuits without another TfL round-trip."""

    @dataclass
    class NotFoundClient:
        calls: list[str] = field(default_factory=list)

        async def fetch_stop_point(self, naptan_id: str) -> TflStopPoint:
            self.calls.append(naptan_id)
            fake_request = httpx.Request("GET", f"/StopPoint/{naptan_id}")
            fake_response = httpx.Response(404, request=fake_request)
            http_exc = httpx.HTTPStatusError(
                "Not Found", request=fake_request, response=fake_response
            )
            raise TflClientError("TfL request failed: HTTP 404") from http_exc

    pool = fake_pool_factory([], [])
    fake_client = NotFoundClient()

    first = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["490DEPRECATED"],
    )
    second = await stations.resolve_naptans(
        pool=pool,
        tfl_client=fake_client,  # type: ignore[arg-type]
        naptan_ids=["490DEPRECATED"],
    )

    assert first == {"490DEPRECATED": None}
    assert second == {"490DEPRECATED": None}
    assert fake_client.calls == ["490DEPRECATED"]
