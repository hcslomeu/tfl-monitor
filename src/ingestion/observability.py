"""Shared Logfire setup for ingestion services."""

from __future__ import annotations

import os

import logfire

INGESTION_SERVICE_NAME = "tfl-monitor-ingestion"

# Head-sample 10% of traces by default to stay under the free-tier (10M
# spans/mo) allowance. The ingestion loop emits the highest volume in the
# stack (kafka.publish/kafka.consume/db.insert spans fire per message), so
# sampling here is what actually moves the bill.
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
        sampling=logfire.SamplingOptions(head=_sample_rate()),
    )
    if instrument_psycopg:
        logfire.instrument_psycopg("psycopg")
