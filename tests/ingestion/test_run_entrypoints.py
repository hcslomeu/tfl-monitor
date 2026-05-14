"""Smoke tests for the collapsed ingestion entrypoints.

`run_producers` / `run_consumers` are thin asyncio.gather wrappers
around the per-topic classes already covered by their own test
modules. We only need to confirm that:

1. The new modules import without error.
2. ``_amain`` exits early with a clear error when required
   environment variables are missing — the production deploy depends
   on this fail-fast behaviour.
"""

from __future__ import annotations

import pytest

from ingestion import run_consumers, run_producers


def test_run_producers_module_importable() -> None:
    assert callable(run_producers.main)
    assert callable(run_producers._amain)


def test_run_consumers_module_importable() -> None:
    assert callable(run_consumers.main)
    assert callable(run_consumers._amain)


@pytest.mark.asyncio
async def test_run_producers_amain_fails_without_kafka(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    with pytest.raises(SystemExit, match="KAFKA_BOOTSTRAP_SERVERS"):
        await run_producers._amain()


@pytest.mark.asyncio
async def test_run_consumers_amain_fails_without_kafka(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    with pytest.raises(SystemExit, match="KAFKA_BOOTSTRAP_SERVERS"):
        await run_consumers._amain()


@pytest.mark.asyncio
async def test_run_consumers_amain_fails_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        await run_consumers._amain()
