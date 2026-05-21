"""Debug-only proxy that forwards typed TfL Unified API calls via Swagger UI.

Gated on ``TFL_DEBUG_PROXY=1`` and ``TFL_APP_KEY`` in the environment. The
router is intentionally NOT part of ``contracts/openapi.yaml``: it exists
so developers can inspect raw TfL payloads from FastAPI's ``/docs`` page
without leaving the IDE or pasting their key into the TfL portal. Never
enable in production.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query

from ingestion.tfl_client import TflClient, TflClientError

__all__ = ["DEFAULT_MODES", "router"]

router = APIRouter(prefix="/api/v1/debug/tfl", tags=["debug-tfl"])

DEFAULT_MODES = "tube,elizabeth-line,overground,dlr"

# Per CLAUDE.md zero-trust rule: validate user-controlled inputs that
# reach the upstream URL path even on debug-only routes. CSV of TfL
# mode slugs (lowercase letters, digits, dashes, commas) — nothing that
# can shape the path (``/``, ``..``, encoded variants).
_MODES_PATTERN = r"^[a-z0-9,-]+$"
_NAPTAN_PATTERN = r"^[0-9A-Za-z]+$"


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Issue an authenticated GET against the TfL Unified API and return raw JSON."""
    try:
        async with TflClient.from_env() as tfl:
            return await tfl._request(path, params=params)  # noqa: SLF001
    except TflClientError as exc:
        # Missing-key is a local misconfiguration, not an upstream
        # failure — surface it as 503 so the response code matches the
        # cause. Anything else from the client wraps an upstream issue.
        message = str(exc)
        status = 503 if "TFL_APP_KEY" in message else 502
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/status", operation_id="debug_tfl_status")
async def debug_status(
    modes: Annotated[
        str, Query(description="CSV of TfL modes", pattern=_MODES_PATTERN)
    ] = DEFAULT_MODES,
) -> Any:
    """``GET /Line/Mode/{modes}/Status`` — basic line statuses without nested disruption."""
    return await _get(f"/Line/Mode/{modes}/Status")


@router.get("/status-detail", operation_id="debug_tfl_status_detail")
async def debug_status_detail(
    modes: Annotated[
        str, Query(description="CSV of TfL modes", pattern=_MODES_PATTERN)
    ] = DEFAULT_MODES,
) -> Any:
    """``GET /Line/Mode/{modes}/Status?detail=true`` — populated ``reason`` and ``disruption``.

    This is the endpoint feeding the *News & reports* widget on tfl.gov.uk;
    ``lineStatuses[].reason`` carries the per-line bulletin text.
    """
    return await _get(f"/Line/Mode/{modes}/Status", params={"detail": "true"})


@router.get("/line-disruption", operation_id="debug_tfl_line_disruption")
async def debug_line_disruption(
    modes: Annotated[
        str, Query(description="CSV of TfL modes", pattern=_MODES_PATTERN)
    ] = DEFAULT_MODES,
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
async def debug_arrivals(
    stop_id: Annotated[str, Path(description="NaPTAN stop id", pattern=_NAPTAN_PATTERN)],
) -> Any:
    """``GET /StopPoint/{stop_id}/Arrivals`` — live arrival predictions for one NaPTAN stop."""
    return await _get(f"/StopPoint/{stop_id}/Arrivals")
