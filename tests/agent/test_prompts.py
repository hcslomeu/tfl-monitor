"""Unit tests for the agent system prompt (``api.agent.prompts``)."""

from __future__ import annotations

from datetime import UTC, datetime

from api.agent.prompts import render


def test_render_substitutes_today() -> None:
    """``{today}`` placeholder is replaced and never leaks into the output."""
    out = render(today="2026-06-02")
    assert "Today is 2026-06-02." in out
    assert "{today}" not in out


def test_render_defaults_today_to_utc_date() -> None:
    """No argument → today's UTC date is substituted."""
    out = render()
    assert "{today}" not in out
    assert f"Today is {datetime.now(UTC).date().isoformat()}." in out


def test_future_trip_rule_suppresses_live_conditions() -> None:
    """Future-trip policy must survive prompt edits.

    A trip planned for a future time must route through ``departure_time``
    and must not pull live status/disruptions (which only describe "now"),
    and a missing time must be asked for rather than guessed.
    """
    lowered = render(today="2026-06-02").lower()
    assert "future trips" in lowered
    assert "departure_time" in lowered
    assert "query_tube_status" in lowered
    assert "query_recent_disruptions" in lowered
    assert "ask for the time" in lowered
