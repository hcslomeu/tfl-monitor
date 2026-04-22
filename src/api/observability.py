"""Logfire configuration for the API service.

Reads ``LOGFIRE_TOKEN`` from the environment. If missing, Logfire runs in
no-op mode so local development and tests do not need credentials.
"""

from __future__ import annotations

import os

import logfire
from fastapi import FastAPI


def configure_observability(app: FastAPI) -> None:
    """Configure Logfire and instrument FastAPI, httpx, and psycopg.

    Args:
        app: FastAPI application to instrument.
    """
    logfire.configure(
        service_name="tfl-monitor-api",
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_fastapi(app)
    logfire.instrument_httpx()
    logfire.instrument_psycopg("psycopg")
