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
from dataclasses import dataclass
from typing import Final

import logfire
import psycopg


@dataclass(frozen=True)
class RetentionRule:
    """One table + age threshold."""

    schema: str
    table: str
    days: int

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
    delete_sql = (
        f"DELETE FROM {rule.qualified} WHERE ingested_at < now() - INTERVAL '{rule.days} days'"
    )
    vacuum_sql = f"VACUUM {rule.qualified}"
    with logfire.span(
        "maintenance.prune.rule",
        table=rule.qualified,
        retention_days=rule.days,
    ):
        async with conn.cursor() as cur:
            await cur.execute(delete_sql)
            count = cur.rowcount
            logfire.info(
                "maintenance.prune.deleted",
                table=rule.qualified,
                deleted_rows=count,
            )
            await cur.execute(vacuum_sql)
    return count


async def _amain() -> int:
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
