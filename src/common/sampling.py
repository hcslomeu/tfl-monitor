"""Shared Logfire sampling helpers."""

from __future__ import annotations

import os

import logfire

__all__ = ["build_sampling_options", "read_sample_rate"]


def read_sample_rate(default: float) -> float:
    """Read ``LOGFIRE_SAMPLE_RATE`` and clamp to ``[0.0, 1.0]``.

    Falls back to ``default`` when the variable is unset or unparseable so
    a malformed value never disables observability outright.

    Args:
        default: Sample rate used when the env var is missing or malformed.

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    raw = os.getenv("LOGFIRE_SAMPLE_RATE")
    if raw is None:
        rate = default
    else:
        try:
            rate = float(raw)
        except ValueError:
            rate = default
    return min(max(rate, 0.0), 1.0)


def build_sampling_options(default_rate: float) -> logfire.SamplingOptions:
    """Return ``SamplingOptions`` that keep all warn+/long traces at 100%.

    Traces containing at least one ``warn`` (or higher) span — or whose
    end-to-end duration exceeds five seconds — are forced through at
    probability ``1.0`` via Logfire's tail sampler. Every other trace is
    sampled at the rate resolved from :func:`read_sample_rate`, so the
    free-tier allowance is protected without ever dropping an error.

    Args:
        default_rate: Background sample rate used when the env override is
            unset; the resolved rate also caps long/error traces' siblings.

    Returns:
        A ``SamplingOptions`` instance ready to pass to ``logfire.configure``.
    """
    return logfire.SamplingOptions.level_or_duration(
        level_threshold="warn",
        background_rate=read_sample_rate(default_rate),
    )
