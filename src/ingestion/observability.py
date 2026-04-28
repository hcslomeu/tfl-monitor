"""Shared Logfire setup for ingestion services."""

from __future__ import annotations

import os

import logfire

INGESTION_SERVICE_NAME = "tfl-monitor-ingestion"


def configure_logfire(*, instrument_psycopg: bool = False) -> None:
    """Configure Logfire for an ingestion service entrypoint.

    Args:
        instrument_psycopg: When ``True`` also enables psycopg span
            instrumentation (consumer-only; producer does not open a
            DB connection).
    """
    logfire.configure(
        service_name=INGESTION_SERVICE_NAME,
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    if instrument_psycopg:
        logfire.instrument_psycopg("psycopg")
