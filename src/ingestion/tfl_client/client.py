"""Async client for the TfL Unified API.

Wraps a single :class:`httpx.AsyncClient`, authenticates via the
``app_key`` query parameter, applies a hand-rolled bounded retry on
transient failures, and parses responses into the tier-1 Pydantic
contracts in :mod:`contracts.schemas.tfl_api`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import datetime
from types import TracebackType
from typing import Any, Self

import httpx
import logfire
from pydantic import TypeAdapter

from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflJourneyResult,
    TflLineResponse,
    TflStopPoint,
    TflStopSearchResponse,
)
from ingestion.tfl_client.retry import TflClientError, with_retry

__all__ = ["TflClient", "TflClientError"]

_TFL_BASE_URL = "https://api.tfl.gov.uk"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_ATTEMPTS = 3

_LINE_RESPONSE_ADAPTER: TypeAdapter[list[TflLineResponse]] = TypeAdapter(list[TflLineResponse])
_ARRIVAL_ADAPTER: TypeAdapter[list[TflArrivalPrediction]] = TypeAdapter(list[TflArrivalPrediction])
_STOP_POINT_ADAPTER: TypeAdapter[TflStopPoint] = TypeAdapter(TflStopPoint)
_STOP_SEARCH_ADAPTER: TypeAdapter[TflStopSearchResponse] = TypeAdapter(TflStopSearchResponse)
_JOURNEY_ADAPTER: TypeAdapter[list[TflJourneyResult]] = TypeAdapter(list[TflJourneyResult])


class TflClient:
    """Async TfL Unified API client returning tier-1 typed responses."""

    def __init__(
        self,
        app_key: str,
        *,
        base_url: str = _TFL_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not app_key:
            raise TflClientError("TFL_APP_KEY is required to call the TfL Unified API")
        if max_attempts < 1:
            raise TflClientError("max_attempts must be >= 1")
        self._app_key = app_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    @classmethod
    def from_env(cls, **kwargs: Any) -> TflClient:
        """Build a :class:`TflClient` reading ``TFL_APP_KEY`` from the environment."""
        app_key = os.environ.get("TFL_APP_KEY", "")
        return cls(app_key=app_key, **kwargs)

    async def __aenter__(self) -> Self:
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def fetch_line_statuses(self, modes: Iterable[str]) -> list[TflLineResponse]:
        """Fetch tier-1 line statuses for the given TfL transport modes."""
        modes_param = self._join_modes(modes)
        data = await self._request(f"/Line/Mode/{modes_param}/Status")
        return _LINE_RESPONSE_ADAPTER.validate_python(data)

    async def fetch_arrivals(self, stop_id: str) -> list[TflArrivalPrediction]:
        """Fetch tier-1 arrival predictions for a NaPTAN stop point."""
        if not stop_id:
            raise TflClientError("stop_id must be a non-empty string")
        data = await self._request(f"/StopPoint/{stop_id}/Arrivals")
        return _ARRIVAL_ADAPTER.validate_python(data)

    async def fetch_stop_point(self, naptan_id: str) -> TflStopPoint:
        """Fetch a single tier-1 stop point by NaPTAN code.

        Used by the API-side station resolver when a NaPTAN surfaced in
        a disruption payload is not present in the static dim_stations
        seed. Returns the full stop-point record (only ``naptan_id`` and
        ``common_name`` are typed; the rest is discarded).
        """
        if not naptan_id:
            raise TflClientError("naptan_id must be a non-empty string")
        data = await self._request(f"/StopPoint/{naptan_id}")
        return _STOP_POINT_ADAPTER.validate_python(data)

    async def fetch_line_disruptions(self, modes: Iterable[str]) -> list[TflLineResponse]:
        """Fetch line-status records with nested disruption details.

        Hits ``/Line/Mode/{modes}/Status?detail=true``, which is the only
        free-tier endpoint that returns populated ``affectedRoutes`` and
        ``affectedStops`` arrays inside each ``lineStatuses[*].disruption``
        object. The bare ``/Line/Mode/{modes}/Disruption`` endpoint always
        returns empty arrays on the free tier (see TM-26).
        """
        modes_param = self._join_modes(modes)
        data = await self._request(
            f"/Line/Mode/{modes_param}/Status",
            params={"detail": "true"},
        )
        return _LINE_RESPONSE_ADAPTER.validate_python(data)

    async def search_stop(self, query: str) -> TflStopSearchResponse:
        """Search stop points by free-text name via ``/StopPoint/Search/{query}``.

        Returns the tier-1 search response whose ``matches`` are ranked by
        TfL relevance; the first match is the best name resolution.
        """
        if not query:
            raise TflClientError("query must be a non-empty string")
        data = await self._request(f"/StopPoint/Search/{query}")
        return _STOP_SEARCH_ADAPTER.validate_python(data)

    async def plan_journey(
        self,
        from_id: str,
        to_id: str,
        *,
        departure_time: datetime | None = None,
        modes: Iterable[str] | None = None,
    ) -> list[TflJourneyResult]:
        """Plan journeys between two StopPoint/NaPTAN ids.

        Hits ``/Journey/JourneyResults/{from_id}/to/{to_id}``. Passing
        StopPoint ids (not names) avoids the TfL HTTP 300 disambiguation
        flow. When ``departure_time`` is given it is sent as a departing
        time in TfL's ``yyyyMMdd``/``HHmm`` format; ``modes`` restricts the
        transport modes considered.

        Args:
            from_id: Origin StopPoint/NaPTAN id.
            to_id: Destination StopPoint/NaPTAN id.
            departure_time: Optional desired departure time.
            modes: Optional iterable of TfL transport modes to allow.

        Returns:
            The tier-1 journey options from the response ``journeys`` array.
        """
        if not from_id or not to_id:
            raise TflClientError("from_id and to_id must be non-empty strings")
        params: dict[str, Any] = {}
        if departure_time is not None:
            params["date"] = departure_time.strftime("%Y%m%d")
            params["time"] = departure_time.strftime("%H%M")
            params["timeIs"] = "Departing"
        if modes is not None:
            params["mode"] = self._join_modes(modes)
        data = await self._request(
            f"/Journey/JourneyResults/{from_id}/to/{to_id}",
            params=params or None,
        )
        return _JOURNEY_ADAPTER.validate_python(data.get("journeys", []))

    async def _request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """Issue a GET request with retry, returning the decoded JSON body."""
        http = self._require_http()
        outbound: dict[str, Any] = {**(params or {}), "app_key": self._app_key}
        traced: dict[str, Any] = {
            key: ("***" if key == "app_key" else value) for key, value in outbound.items()
        }

        with logfire.span("tfl.request", path=path, params=traced):

            async def _call() -> httpx.Response:
                return await http.get(path, params=outbound)

            response = await with_retry(_call, max_attempts=self._max_attempts)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise TflClientError(
                    f"TfL request to {path} failed: HTTP {response.status_code}"
                ) from exc
            return response.json()

    def _require_http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise TflClientError("TflClient is not active; use it as 'async with TflClient(...)'")
        return self._http

    @staticmethod
    def _join_modes(modes: Iterable[str]) -> str:
        joined = ",".join(mode for mode in modes if mode)
        if not joined:
            raise TflClientError("modes must contain at least one non-empty value")
        return joined
