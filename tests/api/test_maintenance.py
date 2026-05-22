"""Unit tests for the retention prune (``api.maintenance``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest

from api import maintenance


@dataclass
class _FakeCursor:
    executed: list[str] = field(default_factory=list)
    rowcount: int = 0
    rowcount_by_sql: dict[str, int] = field(default_factory=dict)

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, sql: str) -> None:
        self.executed.append(sql)
        # Set rowcount based on the executed DELETE so the test asserts
        # on per-rule counts. VACUUM keeps the previous rowcount; it
        # is never consumed by callers.
        for marker, count in self.rowcount_by_sql.items():
            if marker in sql and sql.startswith("DELETE"):
                self.rowcount = count
                break


@dataclass
class _FakeConn:
    cursor_obj: _FakeCursor

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


@asynccontextmanager
async def _patch_connect(
    monkeypatch: pytest.MonkeyPatch, cursor: _FakeCursor
) -> AsyncIterator[_FakeConn]:
    conn = _FakeConn(cursor_obj=cursor)

    async def _fake_connect(*_args: object, **_kwargs: object) -> _FakeConn:
        return conn

    monkeypatch.setattr("api.maintenance.psycopg.AsyncConnection.connect", _fake_connect)
    yield conn


@pytest.mark.asyncio
async def test_prune_runs_delete_then_vacuum_per_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(rowcount_by_sql={"raw.arrivals": 100, "raw.line_status": 5})
    async with _patch_connect(monkeypatch, cursor):
        deleted = await maintenance.prune(
            dsn="fake://",
            rules=(
                maintenance.RetentionRule(schema="raw", table="arrivals", days=7),
                maintenance.RetentionRule(schema="raw", table="line_status", days=30),
            ),
        )

    assert deleted == {"raw.arrivals": 100, "raw.line_status": 5}
    # Each rule produces exactly DELETE then VACUUM, in order.
    assert cursor.executed == [
        "DELETE FROM raw.arrivals WHERE ingested_at < now() - INTERVAL '7 days'",
        "VACUUM raw.arrivals",
        "DELETE FROM raw.line_status WHERE ingested_at < now() - INTERVAL '30 days'",
        "VACUUM raw.line_status",
    ]


@pytest.mark.asyncio
async def test_prune_zero_rows_still_runs_vacuum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even on a quiet day the VACUUM should run — dead tuples linger
    from previous deletes and only VACUUM reclaims their pages."""
    cursor = _FakeCursor(rowcount_by_sql={})
    async with _patch_connect(monkeypatch, cursor):
        deleted = await maintenance.prune(
            dsn="fake://",
            rules=(maintenance.RetentionRule(schema="raw", table="arrivals", days=7),),
        )

    assert deleted == {"raw.arrivals": 0}
    assert any(stmt.startswith("VACUUM") for stmt in cursor.executed)


def test_default_rules_target_only_raw_schema() -> None:
    """Marts must never be pruned by retention — they hold the long-term
    aggregates the API endpoints depend on."""
    schemas = {rule.schema for rule in maintenance.DEFAULT_RULES}
    assert schemas == {"raw"}


def test_default_rules_cover_every_high_volume_raw_table() -> None:
    """Regression guard: a new raw.* table from a future producer must be
    added to DEFAULT_RULES or the warehouse drifts unbounded again."""
    expected_tables = {"arrivals", "line_status", "disruptions"}
    tables = {rule.table for rule in maintenance.DEFAULT_RULES}
    assert tables == expected_tables


def test_arrivals_retention_window_tightest() -> None:
    """Arrivals has the highest write volume and the shortest analytical
    half-life — its retention must stay strictly below line_status's."""
    by_table = {rule.table: rule.days for rule in maintenance.DEFAULT_RULES}
    assert by_table["arrivals"] < by_table["line_status"]


@pytest.mark.asyncio
async def test_amain_exits_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        await maintenance._amain()  # noqa: SLF001
