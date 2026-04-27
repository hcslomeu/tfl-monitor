"""Async JSON Kafka producer wrapping :class:`aiokafka.AIOKafkaProducer`.

Single abstraction with one downstream consumer (the line-status
producer); kept narrow to honour CLAUDE.md "Principle #1" rule 4 — no
factory or registry until a second event type lands (TM-B4).
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import logfire
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from pydantic import BaseModel

__all__ = ["KafkaEventProducer", "KafkaProducerError"]

_DEFAULT_CLIENT_ID = "tfl-monitor-ingestion"
_DEFAULT_LINGER_MS = 10


class KafkaProducerError(RuntimeError):
    """Raised when the Kafka producer cannot publish an event."""


class KafkaEventProducer:
    """Async JSON Kafka producer over ``AIOKafkaProducer``.

    Lifecycle is managed via ``async with``: the underlying producer is
    instantiated and started in ``__aenter__`` and stopped in
    ``__aexit__``. The ``producer_factory`` argument lets unit tests
    replace ``AIOKafkaProducer`` with a fake without monkeypatching
    module attributes.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client_id: str = _DEFAULT_CLIENT_ID,
        producer_factory: Callable[..., AIOKafkaProducer] | None = None,
    ) -> None:
        if not bootstrap_servers:
            raise ValueError("bootstrap_servers must be a non-empty string")
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._producer_factory = producer_factory or AIOKafkaProducer
        self._producer: AIOKafkaProducer | None = None

    async def __aenter__(self) -> Self:
        self._producer = self._producer_factory(
            bootstrap_servers=self._bootstrap_servers,
            client_id=self._client_id,
            enable_idempotence=True,
            acks="all",
            linger_ms=_DEFAULT_LINGER_MS,
        )
        await self._producer.start()  # type: ignore[no-untyped-call]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._producer is not None:
            await self._producer.stop()  # type: ignore[no-untyped-call]
            self._producer = None

    async def publish(
        self,
        topic: str,
        *,
        event: BaseModel,
        key: str | None,
    ) -> None:
        """Serialise ``event`` to JSON and produce it to ``topic``.

        Args:
            topic: Kafka topic name.
            event: Pydantic model serialised via ``model_dump_json()``.
            key: Optional partition key, encoded as UTF-8 bytes when
                provided.
        """
        producer = self._require_producer()
        value = event.model_dump_json().encode("utf-8")
        encoded_key = key.encode("utf-8") if key is not None else None
        attributes: dict[str, Any] = {
            "topic": topic,
            "key": key,
            "event_type": getattr(event, "event_type", event.__class__.__name__),
            "event_class": event.__class__.__name__,
        }
        with logfire.span("kafka.publish", **attributes):
            try:
                await producer.send_and_wait(  # type: ignore[no-untyped-call]
                    topic,
                    value=value,
                    key=encoded_key,
                )
            except KafkaError as exc:
                raise KafkaProducerError(f"Kafka publish to {topic} failed: {exc!r}") from exc

    def _require_producer(self) -> AIOKafkaProducer:
        if self._producer is None:
            raise KafkaProducerError(
                "KafkaEventProducer is not active; use it as 'async with KafkaEventProducer(...)'"
            )
        return self._producer
