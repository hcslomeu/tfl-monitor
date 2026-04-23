"""Integration test for contracts/sql/*.sql executed by Postgres init.

Gated on the DATABASE_URL environment variable so CI and day-to-day unit
runs skip cleanly when Postgres is not reachable. Run locally against
`make up` with:

    DATABASE_URL=postgresql://tflmonitor:change_me@localhost:5432/tflmonitor \
        uv run pytest tests/integration -v
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set; skipping Postgres-dependent integration tests",
)


RAW_TABLES = ("line_status", "arrivals", "disruptions")


@pytest.fixture(scope="module")
def pg_conn():
    """Yield a single psycopg connection for all assertions in this module."""
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


def test_pgcrypto_extension_installed(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'")
        assert cur.fetchone() is not None, "pgcrypto extension missing"


def test_raw_schema_and_tables_exist(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'raw'")
        assert cur.fetchone() is not None, "schema `raw` not created"

        for table in RAW_TABLES:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'raw' AND table_name = %s",
                (table,),
            )
            assert cur.fetchone() is not None, f"table raw.{table} missing"


@pytest.mark.parametrize("table", RAW_TABLES)
def test_raw_event_id_defaults_to_gen_random_uuid(pg_conn, table: str) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_default, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'raw' AND table_name = %s "
            "AND column_name = 'event_id'",
            (table,),
        )
        row = cur.fetchone()
        assert row is not None, f"event_id column missing on raw.{table}"
        column_default, is_nullable = row
        assert column_default is not None and "gen_random_uuid" in column_default, (
            f"raw.{table}.event_id should default to gen_random_uuid(); got {column_default!r}"
        )
        assert is_nullable == "NO", f"raw.{table}.event_id must remain NOT NULL"


@pytest.mark.parametrize("table", RAW_TABLES)
def test_raw_ingested_at_defaults_to_now(pg_conn, table: str) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_default, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'raw' AND table_name = %s "
            "AND column_name = 'ingested_at'",
            (table,),
        )
        row = cur.fetchone()
        assert row is not None, f"ingested_at column missing on raw.{table}"
        column_default, is_nullable = row
        assert column_default is not None and "now()" in column_default.lower(), (
            f"raw.{table}.ingested_at should default to now(); got {column_default!r}"
        )
        assert is_nullable == "NO", f"raw.{table}.ingested_at must remain NOT NULL"


@pytest.mark.parametrize("table", RAW_TABLES)
def test_raw_insert_with_defaults_round_trip(pg_conn, table: str) -> None:
    """Insert supplying only the non-defaulted columns and verify defaults fire."""
    with pg_conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO raw.{table} (event_type, source, payload) "
            "VALUES (%s, %s, %s::jsonb) "
            "RETURNING event_id, ingested_at",
            ("smoke.test", "integration", "{}"),
        )
        event_id, ingested_at = cur.fetchone()
        assert event_id is not None
        assert ingested_at is not None
        cur.execute(f"DELETE FROM raw.{table} WHERE event_id = %s", (event_id,))
    pg_conn.commit()
