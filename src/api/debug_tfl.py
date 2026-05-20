"""Debug-only proxy that forwards typed TfL Unified API calls via Swagger UI.

Gated on ``TFL_DEBUG_PROXY=1`` and ``TFL_APP_KEY`` in the environment. The
router is intentionally NOT part of ``contracts/openapi.yaml``: it exists
so developers can inspect raw TfL payloads from FastAPI's ``/docs`` page
without leaving the IDE or pasting their key into the TfL portal. Never
enable in production.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from ingestion.tfl_client import TflClient, TflClientError

__all__ = ["DEFAULT_MODES", "router"]

router = APIRouter(prefix="/api/v1/debug/tfl", tags=["debug-tfl"])

DEFAULT_MODES = "tube,elizabeth-line,overground,dlr"


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Issue an authenticated GET against the TfL Unified API and return raw JSON."""
    try:
        async with TflClient.from_env() as tfl:
            return await tfl._request(path, params=params)  # noqa: SLF001
    except TflClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/status", operation_id="debug_tfl_status")
async def debug_status(
    modes: Annotated[str, Query(description="CSV of TfL modes")] = DEFAULT_MODES,
) -> Any:
    """``GET /Line/Mode/{modes}/Status`` — basic line statuses without nested disruption."""
    return await _get(f"/Line/Mode/{modes}/Status")


@router.get("/status-detail", operation_id="debug_tfl_status_detail")
async def debug_status_detail(
    modes: Annotated[str, Query(description="CSV of TfL modes")] = DEFAULT_MODES,
) -> Any:
    """``GET /Line/Mode/{modes}/Status?detail=true`` — populated ``reason`` and ``disruption``.

    This is the endpoint feeding the *News & reports* widget on tfl.gov.uk;
    ``lineStatuses[].reason`` carries the per-line bulletin text.
    """
    return await _get(f"/Line/Mode/{modes}/Status", params={"detail": "true"})


@router.get("/line-disruption", operation_id="debug_tfl_line_disruption")
async def debug_line_disruption(
    modes: Annotated[str, Query(description="CSV of TfL modes")] = DEFAULT_MODES,
) -> Any:
    """``GET /Line/Mode/{modes}/Disruption`` — free-tier returns empty arrays (TM-26)."""
    return await _get(f"/Line/Mode/{modes}/Disruption")


@router.get("/yellow-banner", operation_id="debug_tfl_yellow_banner")
async def debug_yellow_banner() -> Any:
    """``GET /status/yellowbannermessages`` — network-wide yellow banner notices."""
    return await _get("/status/yellowbannermessages")


@router.get("/red-banner", operation_id="debug_tfl_red_banner")
async def debug_red_banner() -> Any:
    """``GET /status/redbannermessages`` — network-wide red banner notices."""
    return await _get("/status/redbannermessages")


@router.get("/lift-disruptions", operation_id="debug_tfl_lift_disruptions")
async def debug_lift_disruptions() -> Any:
    """``GET /Disruptions/Lifts/v2`` — current lift and escalator outages."""
    return await _get("/Disruptions/Lifts/v2")


@router.get("/arrivals/{stop_id}", operation_id="debug_tfl_arrivals")
async def debug_arrivals(stop_id: str) -> Any:
    """``GET /StopPoint/{stop_id}/Arrivals`` — live arrival predictions for one NaPTAN stop."""
    return await _get(f"/StopPoint/{stop_id}/Arrivals")
