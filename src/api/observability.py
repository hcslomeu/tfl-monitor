"""Logfire configuration for the API service.

Reads ``LOGFIRE_TOKEN`` from the environment. If missing, Logfire runs in
no-op mode so local development and tests do not need credentials.

Outbound LLM/agent visibility lives in LangSmith (see ``agent/``);
``instrument_fastapi`` surfaces per-endpoint timing here.
"""

from __future__ import annotations

import os

import logfire
from fastapi import FastAPI

from common.sampling import build_sampling_options

_DEFAULT_SAMPLE_RATE = 0.1


def configure_observability(app: FastAPI) -> None:
    """Configure Logfire and instrument FastAPI.

    Args:
        app: FastAPI application to instrument.
    """
    logfire.configure(
        service_name="tfl-monitor-api",
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
        sampling=build_sampling_options(_DEFAULT_SAMPLE_RATE),
    )
    logfire.instrument_fastapi(app)
