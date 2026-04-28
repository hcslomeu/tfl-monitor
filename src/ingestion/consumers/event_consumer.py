"""Generic Kafka → Postgres consumer for tier-2 envelope topics.

Mirrors the failure-isolation contract introduced by TM-B3 for
``line-status``: validate every Kafka message against the topic's
:class:`contracts.schemas.common.Event` subclass, write the validated
envelope into the raw Postgres table, and commit the offset only
after a successful insert.

Failure modes:

- :class:`pydantic.ValidationError` → log + skip + commit (poison pill).
- :class:`psycopg.OperationalError` → log + reconnect + replay
  (no commit).
- Any other exception → log + replay (no commit).

Lag is reported on every ``kafka.consume`` span and refreshed every
``lag_refresh_messages`` messages or every ``lag_refresh_seconds``
seconds, whichever fires first.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, NoReturn

import logfire
import psycopg
import pydantic
from aiokafka.structs import ConsumerRecord, TopicPartition

from contracts.schemas.common import Event
from ingestion.consumers.kafka import KafkaConsumerError, KafkaEventConsumer
from ingestion.consumers.postgres import RawEventWriter

__all__ = [
    "DEFAULT_LAG_REFRESH_MESSAGES",
    "DEFAULT_LAG_REFRESH_SECONDS",
    "RawEventConsumer",
]

DEFAULT_LAG_REFRESH_MESSAGES = 50
DEFAULT_LAG_REFRESH_SECONDS = 30.0
_POISON_PILL_PREVIEW_BYTES = 256
_REPLAY_BACKOFF_SECONDS = 1.0


def _truncate(value: bytes | None, limit: int) -> str:
    if value is None:
        return ""
    return value[:limit].decode("utf-8", errors="replace")


class RawEventConsumer[E: Event[Any]]:
    """Consumes a Kafka topic and writes validated envelopes to Postgres.

    The class is generic over the envelope type ``E`` so each topic
    binds to its tier-2 schema (e.g. ``LineStatusEvent``,
    ``ArrivalEvent``, ``DisruptionEvent``). The writer's ``table`` is
    selected at construction time by the caller's entrypoint.
    """

    def __init__(
        self,
        *,
        kafka_consumer: KafkaEventConsumer,
        writer: RawEventWriter,
        event_class: type[E],
        topic_label: str,
        log_namespace: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        lag_refresh_messages: int = DEFAULT_LAG_REFRESH_MESSAGES,
        lag_refresh_seconds: float = DEFAULT_LAG_REFRESH_SECONDS,
    ) -> None:
        if not topic_label:
            raise ValueError("topic_label must be a non-empty string")
        if log_namespace is not None and not log_namespace:
            raise ValueError("log_namespace must be a non-empty string when provided")
        if lag_refresh_messages <= 0:
            raise ValueError("lag_refresh_messages must be > 0")
        if lag_refresh_seconds <= 0:
            raise ValueError("lag_refresh_seconds must be > 0")
        self._kafka_consumer = kafka_consumer
        self._writer = writer
        self._event_class = event_class
        self._topic_label = topic_label
        # ``log_namespace`` exists so the line-status entrypoint can keep
        # TM-B3's ``ingestion.line_status.*`` log keys after migration —
        # the topic name uses a hyphen, but the historical namespace used
        # an underscore. New topics fall back to ``topic_label`` so their
        # log keys mirror the topic name.
        self._log_namespace = log_namespace or topic_label
        self._clock = clock
        self._lag_refresh_messages = lag_refresh_messages
        self._lag_refresh_seconds = lag_refresh_seconds
        self._cached_lag: dict[int, int] = {}
        self._last_seen_offset: dict[int, int] = {}

    async def run_once(self, max_messages: int | None = None) -> int:
        """Consume up to ``max_messages`` messages then return.

        Returns the number of messages successfully inserted (excludes
        duplicates and skipped poison pills). The production loop calls
        :meth:`run_forever`; tests use this method.
        """
        return await self._run_loop(max_messages)

    async def run_forever(self) -> NoReturn:
        """Run the consume → validate → insert → commit loop forever."""
        await self._run_loop(None)
        raise RuntimeError("RawEventConsumer.run_forever exited unexpectedly")

    async def _run_loop(self, max_messages: int | None) -> int:
        inserted = 0
        seen = 0
        seen_since_refresh = 0
        last_refresh = self._clock()
        async for msg in self._kafka_consumer:
            self._last_seen_offset[msg.partition] = msg.offset
            if await self._process_one(msg):
                inserted += 1
            seen += 1
            seen_since_refresh += 1
            elapsed = self._clock() - last_refresh
            if (
                seen_since_refresh >= self._lag_refresh_messages
                or elapsed >= self._lag_refresh_seconds
            ):
                await self._refresh_lag()
                seen_since_refresh = 0
                last_refresh = self._clock()
            if max_messages is not None and seen >= max_messages:
                break
        return inserted

    async def _process_one(self, msg: ConsumerRecord[bytes, bytes]) -> bool:
        with logfire.span(
            "kafka.consume",
            topic=msg.topic,
            topic_label=self._topic_label,
            partition=msg.partition,
            offset=msg.offset,
            lag=self._cached_lag.get(msg.partition),
        ):
            try:
                event = self._event_class.model_validate_json(msg.value or b"")
            except pydantic.ValidationError as exc:
                logfire.warn(
                    f"ingestion.{self._log_namespace}.poison_pill",
                    error=repr(exc),
                    topic=msg.topic,
                    partition=msg.partition,
                    offset=msg.offset,
                    preview=_truncate(msg.value, _POISON_PILL_PREVIEW_BYTES),
                )
                await self._safe_commit(msg)
                return False

            try:
                rowcount = await self._writer.insert(event)
            except psycopg.OperationalError as exc:
                logfire.warn(
                    f"ingestion.{self._log_namespace}.db_transient",
                    error=repr(exc),
                    event_id=str(event.event_id),
                )
                await self._safe_reconnect()
                self._schedule_replay(msg)
                return False
            except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
                logfire.error(
                    f"ingestion.{self._log_namespace}.unknown_failure",
                    error=repr(exc),
                    event_id=str(event.event_id),
                )
                self._schedule_replay(msg)
                return False

            await self._safe_commit(msg)
            return bool(rowcount)

    async def _safe_commit(self, msg: ConsumerRecord[bytes, bytes]) -> None:
        """Commit the latest offsets; never raise."""
        try:
            await self._kafka_consumer.commit()
        except KafkaConsumerError as exc:
            logfire.warn(
                f"ingestion.{self._log_namespace}.commit_failed",
                error=repr(exc),
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
            )

    async def _safe_reconnect(self) -> None:
        """Reconnect the writer; swallow + back off if the DB stays down.

        Catches a broad ``Exception`` rather than just
        :class:`psycopg.OperationalError` so a non-OperationalError
        raised by the connection factory (timeouts, OS-level errors,
        driver glitches) still leaves the caller free to schedule a
        replay and keep the daemon alive.
        """
        try:
            await self._writer.reconnect()
        except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
            logfire.warn(
                f"ingestion.{self._log_namespace}.reconnect_failed",
                error=repr(exc),
            )
            await asyncio.sleep(_REPLAY_BACKOFF_SECONDS)

    def _schedule_replay(self, msg: ConsumerRecord[bytes, bytes]) -> None:
        """Roll the consumer back to ``msg.offset`` so the next iteration replays it."""
        try:
            self._kafka_consumer.seek(TopicPartition(msg.topic, msg.partition), msg.offset)
        except KafkaConsumerError as exc:
            logfire.warn(
                f"ingestion.{self._log_namespace}.seek_failed",
                error=repr(exc),
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
            )

    async def _refresh_lag(self) -> None:
        partitions = self._kafka_consumer.assignment()
        if not partitions:
            return
        try:
            end_offsets = await self._kafka_consumer.end_offsets(partitions)
        except KafkaConsumerError as exc:
            logfire.warn(
                f"ingestion.{self._log_namespace}.lag_refresh_failed",
                error=repr(exc),
            )
            return
        for tp, end_offset in end_offsets.items():
            last_seen = self._last_seen_offset.get(tp.partition, -1)
            self._cached_lag[tp.partition] = max(0, end_offset - last_seen - 1)
