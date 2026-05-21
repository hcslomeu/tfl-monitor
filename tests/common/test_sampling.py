"""Tests for ``common.sampling`` env-var parsing and SamplingOptions wiring."""

from __future__ import annotations

import logfire
import pytest

from common.sampling import build_sampling_options, read_sample_rate


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGFIRE_SAMPLE_RATE", raising=False)


def test_read_sample_rate_returns_default_when_unset() -> None:
    assert read_sample_rate(0.1) == pytest.approx(0.1)
    assert read_sample_rate(0.5) == pytest.approx(0.5)


def test_read_sample_rate_uses_env_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "0.25")
    assert read_sample_rate(0.1) == pytest.approx(0.25)


def test_read_sample_rate_clamps_above_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "2.0")
    assert read_sample_rate(0.1) == pytest.approx(1.0)


def test_read_sample_rate_clamps_below_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "-0.5")
    assert read_sample_rate(0.1) == pytest.approx(0.0)


def test_read_sample_rate_malformed_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "abc")
    assert read_sample_rate(0.1) == pytest.approx(0.1)


def test_read_sample_rate_empty_string_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "")
    assert read_sample_rate(0.1) == pytest.approx(0.1)


def test_build_sampling_options_returns_logfire_type() -> None:
    options = build_sampling_options(0.1)
    assert isinstance(options, logfire.SamplingOptions)
    # ``level_or_duration`` keeps ``head=1.0`` and pushes selection to the
    # tail callable, so every trace reaches the level/duration check.
    assert options.head == pytest.approx(1.0)
    assert options.tail is not None


def test_build_sampling_options_picks_up_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "0.05")
    options = build_sampling_options(0.5)
    # Resolved rate is bound inside ``options.tail``; assert the constructor
    # consumed it without erroring and produced a usable tail callable.
    assert callable(options.tail)
