"""TfL ``disruptions`` Kafka producer.

Polls :meth:`ingestion.tfl_client.TflClient.fetch_disruptions` on a
fixed-rate cadence, normalises each tier-1 response via
:func:`ingestion.tfl_client.normalise.disruption_payloads`, wraps every
:class:`contracts.schemas.DisruptionPayload` in a
:class:`contracts.schemas.DisruptionEvent` envelope, and produces the
JSON-serialised event to topic ``disruptions``.

The ``event_type`` literal is fixed at ``"disruptions.snapshot"`` so
downstream consumers can filter on it. Disruption datasets are
slow-moving so the default cadence is 5 minutes (one TfL request per
cycle across the same modes the line-status producer covers).
Cycles fail soft: a TfL or Kafka error is logged via Logfire and
the daemon continues on the next tick.
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

from contracts.schemas import DisruptionEvent
from ingestion.observability import configure_logfire
from ingestion.producers.kafka import KafkaEventProducer, KafkaProducerError
from ingestion.tfl_client import TflClient, TflClientError, disruption_payloads

__all__ = [
    "DEFAULT_DISRUPTION_MODES",
    "DISRUPTIONS_EVENT_TYPE",
    "DISRUPTIONS_POLL_PERIOD_SECONDS",
    "DisruptionsProducer",
    "main",
]

DISRUPTIONS_EVENT_TYPE = "disruptions.snapshot"
DISRUPTIONS_POLL_PERIOD_SECONDS = 300.0
DEFAULT_DISRUPTION_MODES: tuple[str, ...] = (
    "tube",
    "elizabeth-line",
    "overground",
    "dlr",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DisruptionsProducer:
    """Polls TfL disruptions and produces events to Kafka."""

    def __init__(
        self,
        *,
        tfl_client: TflClient,
        kafka_producer: KafkaEventProducer,
        modes: Sequence[str] = DEFAULT_DISRUPTION_MODES,
        period_seconds: float = DISRUPTIONS_POLL_PERIOD_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        event_id_factory: Callable[[], UUID] = uuid.uuid4,
    ) -> None:
        if period_seconds <= 0:
            raise ValueError("period_seconds must be > 0")
        if not modes:
            raise ValueError("modes must contain at least one entry")
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
            failure (TfL error, Kafka error), logs and returns the
            partial count; never raises.
        """
        try:
            tier1 = await self._tfl_client.fetch_disruptions(self._modes)
        except TflClientError as exc:
            logfire.warn("ingestion.disruptions.tfl_failed", error=repr(exc))
            return 0
        except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
            logfire.error(
                "ingestion.disruptions.tfl_unexpected_error",
                error=repr(exc),
            )
            return 0

        payloads = disruption_payloads(tier1)
        published = 0
        for payload in payloads:
            event = DisruptionEvent(
                event_id=self._event_id_factory(),
                event_type=DISRUPTIONS_EVENT_TYPE,
                ingested_at=self._clock(),
                payload=payload,
            )
            try:
                await self._kafka_producer.publish(
                    DisruptionEvent.TOPIC_NAME,
                    event=event,
                    key=payload.disruption_id,
                )
                published += 1
            except KafkaProducerError as exc:
                logfire.warn(
                    "ingestion.disruptions.kafka_failed",
                    disruption_id=payload.disruption_id,
                    error=repr(exc),
                )
        logfire.info("ingestion.disruptions.cycle", published=published)
        return published

    async def run_forever(self) -> NoReturn:
        """Run :meth:`run_once` on a fixed-rate cadence forever."""
        while True:
            started = time.monotonic()
            await self.run_once()
            elapsed = time.monotonic() - started
            if elapsed > self._period_seconds:
                logfire.warn(
                    "ingestion.disruptions.cycle_overrun",
                    elapsed=elapsed,
                    period_seconds=self._period_seconds,
                )
            await asyncio.sleep(max(0.0, self._period_seconds - elapsed))


async def _amain() -> None:
    configure_logfire()
    logfire.instrument_httpx()

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    async with (
        TflClient.from_env() as tfl,
        KafkaEventProducer(bootstrap_servers=bootstrap) as kafka,
    ):
        producer = DisruptionsProducer(tfl_client=tfl, kafka_producer=kafka)
        await producer.run_forever()


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.producers.disruptions``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
