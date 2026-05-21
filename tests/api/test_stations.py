"""Unit tests for the hybrid NaPTAN ↔ station-name resolver."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from api import stations
from contracts.schemas.tfl_api import TflStopPoint


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
