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
    """No argument → today's UTC date is substituted.

    Capturing the date either side of ``render()`` tolerates a midnight-UTC
    rollover landing between the two ``now()`` reads.
    """
    before = datetime.now(UTC).date().isoformat()
    out = render()
    after = datetime.now(UTC).date().isoformat()
    assert "{today}" not in out
    assert f"Today is {before}." in out or f"Today is {after}." in out


def test_future_trip_rule_suppresses_live_conditions() -> None:
    """Future-trip policy must survive prompt edits.

    A trip planned for a future time must route through ``departure_time``
    and must not pull live status/disruptions (which only describe "now"),
    and a missing time must be asked for rather than guessed. Whitespace is
    collapsed so the assertions are immune to prompt line-wrapping.
    """
    collapsed = " ".join(render(today="2026-06-02").lower().split())
    assert "future trips" in collapsed
    assert "departure_time as an iso-8601 timestamp" in collapsed
    assert "only the simplest, fastest route" in collapsed
    assert (
        "do not call query_tube_status or query_recent_disruptions for a future trip" in collapsed
    )
    assert "ask for the time before planning" in collapsed
