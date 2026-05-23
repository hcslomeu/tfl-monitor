"""Retention sweep for ``raw.*`` tables.

Driven nightly by ``scripts/cron-retention.sh`` (host cron) so the
warehouse stays bounded under the Supabase free-tier ceiling. dbt
marts already aggregate the raw rows; the retention window is short
because the marts carry the long-term signal.

Usage::

    python -m api.maintenance

Reads ``DATABASE_URL`` from the environment. Exits non-zero (and
flushes Logfire) on any error so cron raises the alarm.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Final

import logfire
import psycopg
from psycopg import sql

MAINTENANCE_SERVICE_NAME = "tfl-monitor-maintenance"

# Defensive identifier guard. Belt-and-braces on top of
# ``psycopg.sql.Identifier`` which already quotes safely; this rejects
# any caller that tries to construct a ``RetentionRule`` with a non-
# identifier schema/table name before it ever reaches the cursor.
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class RetentionRule:
    """One table + age threshold."""

    schema: str
    table: str
    days: int

    def __post_init__(self) -> None:
        for label, value in (("schema", self.schema), ("table", self.table)):
            if not _IDENTIFIER_RE.match(value):
                raise ValueError(f"{label} must match {_IDENTIFIER_RE.pattern}; got {value!r}")
        if self.days <= 0:
            raise ValueError(f"days must be > 0; got {self.days}")

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


# Retention windows. Tuned for the post-hotfix volume:
#  - arrivals at 15 min poll → ~14K rows/day → 7d cap ≈ 100K rows
#  - line_status at 30 s poll → ~40K rows/day → 30d cap ≈ 1.2M rows
#  - disruptions tiny (<1 MB/day) → 30d cap is generous
# Marts hold the long-term aggregates; truncating raw beyond these
# windows costs nothing analytically. Order matters: VACUUM after each
# DELETE so the next rule sees freshly reclaimed disk on a near-full
# Supabase. Arrivals first because it dominates volume.
DEFAULT_RULES: Final[tuple[RetentionRule, ...]] = (
    RetentionRule(schema="raw", table="arrivals", days=7),
    RetentionRule(schema="raw", table="line_status", days=30),
    RetentionRule(schema="raw", table="disruptions", days=30),
)


async def prune(
    *,
    dsn: str,
    rules: tuple[RetentionRule, ...] = DEFAULT_RULES,
) -> dict[str, int]:
    """Delete rows older than each rule's window. Returns deleted counts.

    A VACUUM (without FULL) follows each DELETE to reclaim heap pages
    on the autovacuum-disabled Supabase instance — on a near-full disk
    the DELETE alone leaves dead tuples that still consume space.
    """
    deleted: dict[str, int] = {}
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        for rule in rules:
            count = await _prune_one(conn, rule)
            deleted[rule.qualified] = count
    logfire.info("maintenance.prune.done", deleted=deleted)
    return deleted


async def _prune_one(conn: psycopg.AsyncConnection, rule: RetentionRule) -> int:
    table_ident = sql.Identifier(rule.schema, rule.table)
    delete_stmt = sql.SQL("DELETE FROM {table} WHERE ingested_at < now() - %s::interval").format(
        table=table_ident
    )
    vacuum_stmt = sql.SQL("VACUUM {table}").format(table=table_ident)
    interval_literal = f"{rule.days} days"
    with logfire.span(
        "maintenance.prune.rule",
        table=rule.qualified,
        retention_days=rule.days,
    ):
        async with conn.cursor() as cur:
            await cur.execute(delete_stmt, (interval_literal,))
            count = cur.rowcount
            logfire.info(
                "maintenance.prune.deleted",
                table=rule.qualified,
                deleted_rows=count,
            )
            await cur.execute(vacuum_stmt)
    return count


def _configure_logfire() -> None:
    """Initialise Logfire for the maintenance entrypoint.

    Cron invokes ``python -m api.maintenance`` as a standalone process —
    no FastAPI lifespan or ingestion runner ever sets Logfire up here.
    Without this call the spans below are dropped with a
    ``LogfireNotConfiguredWarning`` and the cron run is observability-blind.
    """
    logfire.configure(
        service_name=MAINTENANCE_SERVICE_NAME,
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_psycopg("psycopg")


async def _amain() -> int:
    _configure_logfire()
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    await prune(dsn=dsn)
    return 0


def main() -> None:
    """Module entrypoint used by ``python -m api.maintenance``."""
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
