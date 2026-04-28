"""TfL ``line-status`` Kafka consumer writing ``raw.line_status`` rows.

Reads the ``line-status`` topic with manual offset management, validates
each message against :class:`contracts.schemas.LineStatusEvent`, inserts
the envelope into Postgres via ``INSERT … ON CONFLICT (event_id) DO
NOTHING``, and commits the Kafka offset only after a successful insert.

Failure isolation:

- :class:`pydantic.ValidationError` → log + skip + commit (poison pill).
- :class:`psycopg.OperationalError` → log + reconnect + replay
  (no commit).
- Any other exception → log + replay (no commit).

Lag is reported on every ``kafka.consume`` span and refreshed every 50
messages or every 30 s, whichever fires first.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import NoReturn

import logfire
import psycopg
import pydantic
from aiokafka.structs import ConsumerRecord, TopicPartition

from contracts.schemas import LineStatusEvent
from ingestion.consumers.kafka import KafkaConsumerError, KafkaEventConsumer
from ingestion.consumers.postgres import RawLineStatusWriter
from ingestion.observability import configure_logfire

__all__ = [
    "LINE_STATUS_CONSUMER_GROUP_ID",
    "LINE_STATUS_LAG_REFRESH_MESSAGES",
    "LINE_STATUS_LAG_REFRESH_SECONDS",
    "LineStatusConsumer",
    "main",
]

LINE_STATUS_CONSUMER_GROUP_ID = "tfl-monitor-line-status-writer"
LINE_STATUS_LAG_REFRESH_MESSAGES = 50
LINE_STATUS_LAG_REFRESH_SECONDS = 30.0
_POISON_PILL_PREVIEW_BYTES = 256
_REPLAY_BACKOFF_SECONDS = 1.0


def _truncate(value: bytes | None, limit: int) -> str:
    if value is None:
        return ""
    return value[:limit].decode("utf-8", errors="replace")


class LineStatusConsumer:
    """Consumes ``line-status`` and writes ``raw.line_status`` rows."""

    def __init__(
        self,
        *,
        kafka_consumer: KafkaEventConsumer,
        writer: RawLineStatusWriter,
        clock: Callable[[], float] = time.monotonic,
        lag_refresh_messages: int = LINE_STATUS_LAG_REFRESH_MESSAGES,
        lag_refresh_seconds: float = LINE_STATUS_LAG_REFRESH_SECONDS,
    ) -> None:
        if lag_refresh_messages <= 0:
            raise ValueError("lag_refresh_messages must be > 0")
        if lag_refresh_seconds <= 0:
            raise ValueError("lag_refresh_seconds must be > 0")
        self._kafka_consumer = kafka_consumer
        self._writer = writer
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
        raise RuntimeError("LineStatusConsumer.run_forever exited unexpectedly")

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
            partition=msg.partition,
            offset=msg.offset,
            lag=self._cached_lag.get(msg.partition),
        ):
            try:
                event = LineStatusEvent.model_validate_json(msg.value or b"")
            except pydantic.ValidationError as exc:
                logfire.warn(
                    "ingestion.line_status.poison_pill",
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
                    "ingestion.line_status.db_transient",
                    error=repr(exc),
                    event_id=str(event.event_id),
                )
                await self._safe_reconnect()
                self._schedule_replay(msg)
                return False
            except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
                logfire.error(
                    "ingestion.line_status.unknown_failure",
                    error=repr(exc),
                    event_id=str(event.event_id),
                )
                self._schedule_replay(msg)
                return False

            await self._safe_commit(msg)
            return bool(rowcount)

    async def _safe_commit(self, msg: ConsumerRecord[bytes, bytes]) -> None:
        """Commit the latest offsets; never raise.

        A failed commit only delays the offset update by one cycle —
        the next successful commit picks up the latest position. We
        never crash the daemon on a transient broker hiccup.
        """
        try:
            await self._kafka_consumer.commit()
        except KafkaConsumerError as exc:
            logfire.warn(
                "ingestion.line_status.commit_failed",
                error=repr(exc),
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
            )

    async def _safe_reconnect(self) -> None:
        """Reconnect the writer; swallow + back off if the DB stays down.

        Catches a broad ``Exception`` rather than just
        :class:`psycopg.OperationalError` so a non-OperationalError raised
        by the connection factory (timeouts, OS-level errors, driver
        glitches) still leaves the caller free to schedule a replay and
        keep the daemon alive. Replay is enforced by
        :meth:`_schedule_replay`.
        """
        try:
            await self._writer.reconnect()
        except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
            logfire.warn(
                "ingestion.line_status.reconnect_failed",
                error=repr(exc),
            )
            await asyncio.sleep(_REPLAY_BACKOFF_SECONDS)

    def _schedule_replay(self, msg: ConsumerRecord[bytes, bytes]) -> None:
        """Roll the consumer back to ``msg.offset`` so the next iteration replays it.

        ``aiokafka`` advances the in-memory fetch position when a record
        is consumed from the iterator; without ``seek`` the failed
        message is skipped even though no offset was committed. Any
        seek failure is logged but never propagated.
        """
        try:
            self._kafka_consumer.seek(TopicPartition(msg.topic, msg.partition), msg.offset)
        except KafkaConsumerError as exc:
            logfire.warn(
                "ingestion.line_status.seek_failed",
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
                "ingestion.line_status.lag_refresh_failed",
                error=repr(exc),
            )
            return
        for tp, end_offset in end_offsets.items():
            last_seen = self._last_seen_offset.get(tp.partition, -1)
            self._cached_lag[tp.partition] = max(0, end_offset - last_seen - 1)


async def _amain() -> None:
    configure_logfire(instrument_psycopg=True)

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    async with (
        KafkaEventConsumer(
            LineStatusEvent.TOPIC_NAME,
            bootstrap_servers=bootstrap,
            group_id=LINE_STATUS_CONSUMER_GROUP_ID,
        ) as kafka,
        RawLineStatusWriter(dsn) as writer,
    ):
        consumer = LineStatusConsumer(kafka_consumer=kafka, writer=writer)
        await consumer.run_forever()


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.consumers.line_status``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
