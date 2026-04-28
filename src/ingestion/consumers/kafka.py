"""Async JSON Kafka consumer wrapping :class:`aiokafka.AIOKafkaConsumer`.

Mirror of :class:`ingestion.producers.KafkaEventProducer`: a thin
abstraction with one downstream consumer (the line-status writer),
kept narrow per CLAUDE.md "Principle #1" rule 4 — no factory or
registry until a second consumer lands (TM-B4).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable, Iterable
from types import TracebackType
from typing import Self, cast

import logfire
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from aiokafka.structs import ConsumerRecord, TopicPartition

__all__ = ["KafkaConsumerError", "KafkaEventConsumer"]

_DEFAULT_CLIENT_ID = "tfl-monitor-ingestion-line-status-consumer"


class KafkaConsumerError(RuntimeError):
    """Raised when the underlying consumer cannot start, commit, or fetch offsets."""


class KafkaEventConsumer:
    """Async Kafka consumer over ``AIOKafkaConsumer``.

    Lifecycle is managed via ``async with``: the underlying consumer is
    instantiated and started in ``__aenter__`` and stopped in
    ``__aexit__``. The ``consumer_factory`` argument lets unit tests
    replace ``AIOKafkaConsumer`` with a fake without monkeypatching
    module attributes.
    """

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str,
        *,
        group_id: str,
        client_id: str = _DEFAULT_CLIENT_ID,
        auto_offset_reset: str = "earliest",
        consumer_factory: Callable[..., AIOKafkaConsumer] | None = None,
    ) -> None:
        if not topic:
            raise ValueError("topic must be a non-empty string")
        if not bootstrap_servers:
            raise ValueError("bootstrap_servers must be a non-empty string")
        if not group_id:
            raise ValueError("group_id must be a non-empty string")
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._client_id = client_id
        self._auto_offset_reset = auto_offset_reset
        self._consumer_factory = consumer_factory or AIOKafkaConsumer
        self._consumer: AIOKafkaConsumer | None = None

    async def __aenter__(self) -> Self:
        consumer = self._consumer_factory(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
            group_id=self._group_id,
            auto_offset_reset=self._auto_offset_reset,
            enable_auto_commit=False,
        )
        self._consumer = consumer
        with logfire.span("kafka.consumer.start", topic=self._topic, group_id=self._group_id):
            try:
                await consumer.start()  # type: ignore[no-untyped-call]
            except KafkaError as exc:
                with contextlib.suppress(Exception):
                    await consumer.stop()  # type: ignore[no-untyped-call]
                self._consumer = None
                raise KafkaConsumerError(f"Kafka consumer start failed: {exc!r}") from exc
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._consumer is not None:
            with logfire.span("kafka.consumer.stop", topic=self._topic):
                await self._consumer.stop()  # type: ignore[no-untyped-call]
            self._consumer = None

    def __aiter__(self) -> AsyncIterator[ConsumerRecord[bytes, bytes]]:
        consumer = self._require_consumer()
        return cast(
            AsyncIterator[ConsumerRecord[bytes, bytes]],
            consumer.__aiter__(),  # type: ignore[no-untyped-call]
        )

    async def commit(self) -> None:
        """Commit the latest offsets for the consumer's assigned partitions."""
        consumer = self._require_consumer()
        with logfire.span("kafka.consumer.commit", topic=self._topic):
            try:
                await consumer.commit()  # type: ignore[no-untyped-call]
            except KafkaError as exc:
                raise KafkaConsumerError(f"Kafka commit failed: {exc!r}") from exc

    async def end_offsets(self, partitions: Iterable[TopicPartition]) -> dict[TopicPartition, int]:
        """Return the broker's end offset for each partition in ``partitions``."""
        consumer = self._require_consumer()
        partitions_list = list(partitions)
        with logfire.span(
            "kafka.consumer.end_offsets",
            topic=self._topic,
            partition_count=len(partitions_list),
        ):
            try:
                return await consumer.end_offsets(partitions_list)  # type: ignore[no-untyped-call,no-any-return]
            except KafkaError as exc:
                raise KafkaConsumerError(f"Kafka end_offsets failed: {exc!r}") from exc

    def assignment(self) -> set[TopicPartition]:
        """Return the partitions currently assigned to the consumer."""
        consumer = self._require_consumer()
        return set(consumer.assignment())  # type: ignore[no-untyped-call]

    def seek(self, partition: TopicPartition, offset: int) -> None:
        """Roll the in-memory fetch position back to ``offset`` for ``partition``.

        Used to replay a message after a downstream failure so the next
        ``__aiter__`` call re-yields it. ``aiokafka.AIOKafkaConsumer.seek``
        is sync; ``KafkaError`` is wrapped into ``KafkaConsumerError``.
        """
        consumer = self._require_consumer()
        try:
            consumer.seek(partition, offset)  # type: ignore[no-untyped-call]
        except KafkaError as exc:
            raise KafkaConsumerError(f"Kafka seek failed: {exc!r}") from exc

    def _require_consumer(self) -> AIOKafkaConsumer:
        if self._consumer is None:
            raise KafkaConsumerError(
                "KafkaEventConsumer is not active; use it as 'async with KafkaEventConsumer(...)'"
            )
        return self._consumer
