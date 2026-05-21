"""Tests for ``common.sampling`` env-var parsing and SamplingOptions wiring."""

from __future__ import annotations

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


def _bound_background_rate(options: logfire.SamplingOptions) -> float:
    """Probe the rate captured by Logfire's tail-sampler closure.

    ``SamplingOptions.level_or_duration`` returns a closure over
    ``background_rate``; reaching into ``__closure__`` is the only public
    way to assert that the resolved sample rate actually made it into the
    options without standing up a real Logfire backend.
    """
    tail = options.tail
    assert tail is not None
    freevars = tail.__code__.co_freevars
    closure = tail.__closure__
    assert closure is not None
    cells = dict(zip(freevars, closure, strict=True))
    value = cells["background_rate"].cell_contents
    assert isinstance(value, float)
    return value


def test_build_sampling_options_returns_logfire_type() -> None:
    options = build_sampling_options(0.1)
    assert isinstance(options, logfire.SamplingOptions)
    # ``level_or_duration`` keeps ``head=1.0`` and pushes selection to the
    # tail callable, so every trace reaches the level/duration check.
    assert options.head == pytest.approx(1.0)
    assert options.tail is not None


def test_build_sampling_options_binds_default_when_env_unset() -> None:
    options = build_sampling_options(0.42)
    assert _bound_background_rate(options) == pytest.approx(0.42)


def test_build_sampling_options_picks_up_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "0.05")
    options = build_sampling_options(0.5)
    assert _bound_background_rate(options) == pytest.approx(0.05)


def test_build_sampling_options_clamps_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_SAMPLE_RATE", "5.0")
    options = build_sampling_options(0.1)
    assert _bound_background_rate(options) == pytest.approx(1.0)
