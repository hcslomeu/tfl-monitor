"""Shared fixtures and HTTP/Kafka/DB doubles for ingestion tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from aiokafka.structs import ConsumerRecord, TopicPartition

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tfl"


def _load(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
def line_status_tube_fixture() -> list[dict[str, Any]]:
    return _load("line_status_tube.json")


@pytest.fixture
def line_status_multi_mode_fixture() -> list[dict[str, Any]]:
    return _load("line_status_multi_mode.json")


@pytest.fixture
def arrivals_oxford_circus_fixture() -> list[dict[str, Any]]:
    return _load("arrivals_oxford_circus.json")


@pytest.fixture
def disruptions_tube_fixture() -> list[dict[str, Any]]:
    return _load("disruptions_tube.json")


ResponseFactory = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def make_transport() -> Callable[[ResponseFactory], httpx.MockTransport]:
    """Return a factory that wires a response handler to ``httpx.MockTransport``."""

    def _make(handler: ResponseFactory) -> httpx.MockTransport:
        return httpx.MockTransport(handler)

    return _make


@pytest.fixture
def script_responses() -> Callable[[list[httpx.Response]], ResponseFactory]:
    """Return a handler factory that replays a fixed list of responses in order."""

    def _factory(responses: list[httpx.Response]) -> ResponseFactory:
        queue: Iterator[httpx.Response] = iter(responses)

        def _handler(_request: httpx.Request) -> httpx.Response:
            try:
                return next(queue)
            except StopIteration as exc:  # pragma: no cover - defensive
                raise AssertionError(
                    "MockTransport received more requests than scripted responses"
                ) from exc

        return _handler

    return _factory


# ---------------------------------------------------------------------------
# Consumer test doubles (Kafka + Postgres)
# ---------------------------------------------------------------------------


def make_consumer_record(
    *,
    value: bytes,
    topic: str = "line-status",
    partition: int = 0,
    offset: int = 0,
    key: bytes | None = None,
) -> ConsumerRecord[bytes, bytes]:
    """Construct a minimal ``ConsumerRecord`` for unit tests."""
    return ConsumerRecord(
        topic=topic,
        partition=partition,
        offset=offset,
        timestamp=0,
        timestamp_type=0,
        key=key,
        value=value,
        checksum=None,
        serialized_key_size=len(key) if key is not None else -1,
        serialized_value_size=len(value),
        headers=(),
    )


class FakeAIOKafkaConsumer:
    """In-memory stand-in for ``AIOKafkaConsumer`` used by unit tests."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args: tuple[Any, ...] = args
        self.kwargs: dict[str, Any] = dict(kwargs)
        self.started = False
        self.stopped = False
        self.commit_count = 0
        self.seeks: list[tuple[TopicPartition, int]] = []
        self.end_offsets_calls: list[list[TopicPartition]] = []
        self._records: list[ConsumerRecord[bytes, bytes]] = []
        self._end_offsets: dict[TopicPartition, int] = {}
        self.commit_fail_next: BaseException | None = None
        self.end_offsets_fail_next: BaseException | None = None
        self.seek_fail_next: BaseException | None = None
        self.start_fail: BaseException | None = None

    # -- test setup helpers --

    def queue(self, record: ConsumerRecord[bytes, bytes]) -> None:
        self._records.append(record)

    def set_end_offsets(self, mapping: dict[TopicPartition, int]) -> None:
        self._end_offsets = dict(mapping)

    # -- AIOKafkaConsumer surface --

    async def start(self) -> None:
        if self.start_fail is not None:
            raise self.start_fail
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def commit(self) -> None:
        if self.commit_fail_next is not None:
            exc = self.commit_fail_next
            self.commit_fail_next = None
            raise exc
        self.commit_count += 1

    async def end_offsets(self, partitions: Iterable[TopicPartition]) -> dict[TopicPartition, int]:
        partitions_list = list(partitions)
        self.end_offsets_calls.append(partitions_list)
        if self.end_offsets_fail_next is not None:
            exc = self.end_offsets_fail_next
            self.end_offsets_fail_next = None
            raise exc
        return {tp: self._end_offsets.get(tp, 0) for tp in partitions_list}

    def assignment(self) -> set[TopicPartition]:
        return set(self._end_offsets.keys())

    def seek(self, partition: TopicPartition, offset: int) -> None:
        if self.seek_fail_next is not None:
            exc = self.seek_fail_next
            self.seek_fail_next = None
            raise exc
        self.seeks.append((partition, offset))

    def __aiter__(self) -> AsyncIterator[ConsumerRecord[bytes, bytes]]:
        records = list(self._records)

        async def _iter() -> AsyncIterator[ConsumerRecord[bytes, bytes]]:
            for record in records:
                yield record

        return _iter()


class FakeCursor:
    """Cursor stand-in returned by :class:`FakeAsyncConnection.execute`."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeAsyncConnection:
    """In-memory stand-in for ``psycopg.AsyncConnection``."""

    def __init__(self, *, default_rowcount: int = 1) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False
        self.default_rowcount = default_rowcount
        self.execute_fail_next: BaseException | None = None
        self.close_fail: BaseException | None = None

    async def execute(self, query: str, params: tuple[Any, ...]) -> FakeCursor:
        if self.execute_fail_next is not None:
            exc = self.execute_fail_next
            self.execute_fail_next = None
            raise exc
        self.executed.append((query, params))
        return FakeCursor(self.default_rowcount)

    async def close(self) -> None:
        if self.close_fail is not None:
            raise self.close_fail
        self.closed = True
