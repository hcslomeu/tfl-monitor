"""Tests for ``common.sampling`` env-var parsing and SamplingOptions wiring."""

from __future__ import annotations

from unittest.mock import patch

import logfire
import pytest

from common.sampling import _read_sample_rate, build_sampling_options


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGFIRE_SAMPLE_RATE", raising=False)


def test_read_sample_rate_returns_default_when_unset() -> None:
    assert _read_sample_rate(0.1) == pytest.approx(0.1)
    assert _read_sample_rate(0.5) == pytest.approx(0.5)


def test_read_sample_rate_uses_env_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "0.25")
    assert _read_sample_rate(0.1) == pytest.approx(0.25)


def test_read_sample_rate_clamps_above_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "2.0")
    assert _read_sample_rate(0.1) == pytest.approx(1.0)


def test_read_sample_rate_clamps_below_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "-0.5")
    assert _read_sample_rate(0.1) == pytest.approx(0.0)


def test_read_sample_rate_malformed_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "abc")
    assert _read_sample_rate(0.1) == pytest.approx(0.1)


def test_read_sample_rate_empty_string_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "")
    assert _read_sample_rate(0.1) == pytest.approx(0.1)


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_read_sample_rate_non_finite_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", raw)
    assert _read_sample_rate(0.1) == pytest.approx(0.1)


def test_build_sampling_options_returns_logfire_type() -> None:
    options = build_sampling_options(0.1)
    assert isinstance(options, logfire.SamplingOptions)


def test_build_sampling_options_forwards_default_to_level_or_duration() -> None:
    with patch.object(
        logfire.SamplingOptions,
        "level_or_duration",
        wraps=logfire.SamplingOptions.level_or_duration,
    ) as spy:
        build_sampling_options(0.42)
    spy.assert_called_once_with(level_threshold="warn", background_rate=pytest.approx(0.42))


def test_build_sampling_options_forwards_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "0.05")
    with patch.object(
        logfire.SamplingOptions,
        "level_or_duration",
        wraps=logfire.SamplingOptions.level_or_duration,
    ) as spy:
        build_sampling_options(0.5)
    spy.assert_called_once_with(level_threshold="warn", background_rate=pytest.approx(0.05))


def test_build_sampling_options_forwards_clamped_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "5.0")
    with patch.object(
        logfire.SamplingOptions,
        "level_or_duration",
        wraps=logfire.SamplingOptions.level_or_duration,
    ) as spy:
        build_sampling_options(0.1)
    spy.assert_called_once_with(level_threshold="warn", background_rate=pytest.approx(1.0))
