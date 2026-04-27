"""TfL ``line-status`` Kafka producer.

Polls :meth:`ingestion.tfl_client.TflClient.fetch_line_statuses` on a
fixed-rate cadence, normalises each tier-1 response via
:func:`ingestion.tfl_client.normalise.line_status_payloads`, wraps every
:class:`contracts.schemas.LineStatusPayload` in a
:class:`contracts.schemas.LineStatusEvent` envelope, and produces the
JSON-serialised event to topic ``line-status``.

The ``event_type`` literal is fixed at ``"line-status.snapshot"`` so
downstream consumers (TM-B3+) can filter on it. Cycles fail soft: a
TfL or Kafka error is logged via Logfire and the daemon continues on
the next tick.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

import logfire

from contracts.schemas import LineStatusEvent
from ingestion.producers.kafka import KafkaEventProducer, KafkaProducerError
from ingestion.tfl_client import TflClient, TflClientError, line_status_payloads

__all__ = [
    "DEFAULT_LINE_STATUS_MODES",
    "LINE_STATUS_EVENT_TYPE",
    "LINE_STATUS_POLL_PERIOD_SECONDS",
    "LineStatusProducer",
    "main",
]

LINE_STATUS_EVENT_TYPE = "line-status.snapshot"
LINE_STATUS_POLL_PERIOD_SECONDS = 30.0
DEFAULT_LINE_STATUS_MODES: tuple[str, ...] = (
    "tube",
    "elizabeth-line",
    "overground",
    "dlr",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LineStatusProducer:
    """Polls TfL line-status and produces events to Kafka."""

    def __init__(
        self,
        *,
        tfl_client: TflClient,
        kafka_producer: KafkaEventProducer,
        modes: Sequence[str] = DEFAULT_LINE_STATUS_MODES,
        period_seconds: float = LINE_STATUS_POLL_PERIOD_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        event_id_factory: Callable[[], UUID] = uuid.uuid4,
    ) -> None:
        if period_seconds <= 0:
            raise ValueError("period_seconds must be > 0")
        self._tfl_client = tfl_client
        self._kafka_producer = kafka_producer
        self._modes = tuple(modes)
        self._period_seconds = period_seconds
        self._clock = clock
        self._event_id_factory = event_id_factory

    async def run_once(self) -> int:
        """Fetch one TfL snapshot and publish all derived events.

        Returns:
            Number of events successfully published. On any recoverable
            failure (TfL error, Kafka error), logs and returns ``0`` for
            TfL errors or the partial count for Kafka errors. Never
            raises.
        """
        try:
            tier1 = await self._tfl_client.fetch_line_statuses(self._modes)
        except TflClientError as exc:
            logfire.warn("ingestion.line_status.tfl_failed", error=repr(exc))
            return 0
        except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
            logfire.error(
                "ingestion.line_status.tfl_unexpected_error",
                error=repr(exc),
            )
            return 0

        payloads = line_status_payloads(tier1)
        published = 0
        for payload in payloads:
            event = LineStatusEvent(
                event_id=self._event_id_factory(),
                event_type=LINE_STATUS_EVENT_TYPE,
                ingested_at=self._clock(),
                payload=payload,
            )
            try:
                await self._kafka_producer.publish(
                    LineStatusEvent.TOPIC_NAME,
                    event=event,
                    key=payload.line_id,
                )
                published += 1
            except KafkaProducerError as exc:
                logfire.warn(
                    "ingestion.line_status.kafka_failed",
                    line_id=payload.line_id,
                    error=repr(exc),
                )
        logfire.info("ingestion.line_status.cycle", published=published)
        return published

    async def run_forever(self) -> NoReturn:
        """Run :meth:`run_once` on a fixed-rate cadence forever."""
        while True:
            started = time.monotonic()
            await self.run_once()
            elapsed = time.monotonic() - started
            if elapsed > self._period_seconds:
                logfire.warn(
                    "ingestion.line_status.cycle_overrun",
                    elapsed=elapsed,
                    period_seconds=self._period_seconds,
                )
            await asyncio.sleep(max(0.0, self._period_seconds - elapsed))


async def _amain() -> None:
    logfire.configure(
        service_name="tfl-monitor-ingestion",
        service_version=os.getenv("APP_VERSION", "0.0.1"),
        environment=os.getenv("ENVIRONMENT", "local"),
        send_to_logfire="if-token-present",
    )
    logfire.instrument_httpx()

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    async with (
        TflClient.from_env() as tfl,
        KafkaEventProducer(bootstrap_servers=bootstrap) as kafka,
    ):
        producer = LineStatusProducer(tfl_client=tfl, kafka_producer=kafka)
        await producer.run_forever()


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.producers.line_status``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
