"""Logfire configuration for the API service.

Reads ``LOGFIRE_TOKEN`` from the environment. If missing, Logfire runs in
no-op mode so local development and tests do not need credentials.
"""

from __future__ import annotations

import os

import logfire
from fastapi import FastAPI

# Head-sample 10% of traces by default to keep the free-tier (10M spans/mo)
# from filling up in days. Override with ``LOGFIRE_SAMPLE_RATE`` (0.0-1.0) for
# debugging windows when full fidelity is needed.
_DEFAULT_SAMPLE_RATE = 0.1


def _sample_rate() -> float:
    raw = os.getenv("LOGFIRE_SAMPLE_RATE")
    if raw is None:
        return _DEFAULT_SAMPLE_RATE
    try:
        rate = float(raw)
    except ValueError:
        return _DEFAULT_SAMPLE_RATE
    return min(max(rate, 0.0), 1.0)


def configure_observability(app: FastAPI) -> None:
    """Configure Logfire and instrument FastAPI."""
    logfire.configure(
        service_name="tfl-monitor-api",
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
        sampling=logfire.SamplingOptions(head=_sample_rate()),
    )
    logfire.instrument_fastapi(app)
