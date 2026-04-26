"""Async client for the TfL Unified API.

Wraps a single :class:`httpx.AsyncClient`, authenticates via the
``app_key`` query parameter, applies a hand-rolled bounded retry on
transient failures, and parses responses into the tier-1 Pydantic
contracts in :mod:`contracts.schemas.tfl_api`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from types import TracebackType
from typing import Any, Self

import httpx
import logfire
from pydantic import TypeAdapter

from contracts.schemas.tfl_api import (
    TflArrivalPrediction,
    TflDisruption,
    TflLineResponse,
)
from ingestion.tfl_client.retry import TflClientError, with_retry

__all__ = ["TflClient", "TflClientError"]

_TFL_BASE_URL = "https://api.tfl.gov.uk"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_ATTEMPTS = 3

_LINE_RESPONSE_ADAPTER: TypeAdapter[list[TflLineResponse]] = TypeAdapter(list[TflLineResponse])
_ARRIVAL_ADAPTER: TypeAdapter[list[TflArrivalPrediction]] = TypeAdapter(list[TflArrivalPrediction])
_DISRUPTION_ADAPTER: TypeAdapter[list[TflDisruption]] = TypeAdapter(list[TflDisruption])


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

    async def fetch_disruptions(self, modes: Iterable[str]) -> list[TflDisruption]:
        """Fetch tier-1 disruptions for the given TfL transport modes."""
        modes_param = self._join_modes(modes)
        data = await self._request(f"/Line/Mode/{modes_param}/Disruption")
        return _DISRUPTION_ADAPTER.validate_python(data)

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
