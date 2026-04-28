"""TfL ``arrivals`` Kafka producer.

Polls :meth:`ingestion.tfl_client.TflClient.fetch_arrivals` for a fixed
list of NaPTAN stop ids on a fixed-rate cadence, normalises each
tier-1 response via
:func:`ingestion.tfl_client.normalise.arrival_payloads`, wraps every
:class:`contracts.schemas.ArrivalPayload` in a
:class:`contracts.schemas.ArrivalEvent` envelope, and produces the
JSON-serialised event to topic ``arrivals``.

Per-stop fetches run sequentially: at the prototype's poll cadence
(30 s) and stop count (5), the round-trip budget is well below the
TfL 500-requests/min cap and concurrency would be premature
optimisation (CLAUDE.md "Principle #1" rule 4). The ``event_type``
literal is fixed at ``"arrivals.snapshot"`` so downstream consumers
can filter on it. Cycles fail soft: a TfL or Kafka error is logged
via Logfire and the daemon continues on the next tick.
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

from contracts.schemas import ArrivalEvent
from ingestion.observability import configure_logfire
from ingestion.producers.kafka import KafkaEventProducer, KafkaProducerError
from ingestion.tfl_client import TflClient, TflClientError, arrival_payloads

__all__ = [
    "ARRIVALS_EVENT_TYPE",
    "ARRIVALS_POLL_PERIOD_SECONDS",
    "ArrivalsProducer",
    "DEFAULT_ARRIVAL_STOPS",
    "main",
]

ARRIVALS_EVENT_TYPE = "arrivals.snapshot"
ARRIVALS_POLL_PERIOD_SECONDS = 30.0

# Major Underground hubs covering high passenger volume across the
# zone-1 core. NaPTAN stop-area identifiers (TfL surface IDs).
DEFAULT_ARRIVAL_STOPS: tuple[str, ...] = (
    "940GZZLUOXC",  # Oxford Circus
    "940GZZLUKSX",  # King's Cross St Pancras
    "940GZZLUWLO",  # Waterloo
    "940GZZLUBNK",  # Bank
    "940GZZLULVT",  # Liverpool Street
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ArrivalsProducer:
    """Polls TfL arrivals across a fixed list of stop ids and produces events."""

    def __init__(
        self,
        *,
        tfl_client: TflClient,
        kafka_producer: KafkaEventProducer,
        stops: Sequence[str] = DEFAULT_ARRIVAL_STOPS,
        period_seconds: float = ARRIVALS_POLL_PERIOD_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        event_id_factory: Callable[[], UUID] = uuid.uuid4,
    ) -> None:
        if period_seconds <= 0:
            raise ValueError("period_seconds must be > 0")
        if not stops:
            raise ValueError("stops must contain at least one NaPTAN id")
        self._tfl_client = tfl_client
        self._kafka_producer = kafka_producer
        self._stops = tuple(stops)
        self._period_seconds = period_seconds
        self._clock = clock
        self._event_id_factory = event_id_factory

    async def run_once(self) -> int:
        """Fetch one TfL snapshot per stop and publish all derived events.

        Returns:
            Number of events successfully published. On any recoverable
            failure (per-stop TfL error, per-event Kafka error), logs
            and continues; never raises.
        """
        published = 0
        for stop_id in self._stops:
            try:
                tier1 = await self._tfl_client.fetch_arrivals(stop_id)
            except TflClientError as exc:
                logfire.warn(
                    "ingestion.arrivals.tfl_failed",
                    stop_id=stop_id,
                    error=repr(exc),
                )
                continue
            except Exception as exc:  # noqa: BLE001 - safety net keeps daemon alive
                logfire.error(
                    "ingestion.arrivals.tfl_unexpected_error",
                    stop_id=stop_id,
                    error=repr(exc),
                )
                continue

            for payload in arrival_payloads(tier1):
                event = ArrivalEvent(
                    event_id=self._event_id_factory(),
                    event_type=ARRIVALS_EVENT_TYPE,
                    ingested_at=self._clock(),
                    payload=payload,
                )
                try:
                    await self._kafka_producer.publish(
                        ArrivalEvent.TOPIC_NAME,
                        event=event,
                        key=payload.station_id,
                    )
                    published += 1
                except KafkaProducerError as exc:
                    logfire.warn(
                        "ingestion.arrivals.kafka_failed",
                        stop_id=stop_id,
                        arrival_id=payload.arrival_id,
                        error=repr(exc),
                    )
        logfire.info("ingestion.arrivals.cycle", published=published)
        return published

    async def run_forever(self) -> NoReturn:
        """Run :meth:`run_once` on a fixed-rate cadence forever."""
        while True:
            started = time.monotonic()
            await self.run_once()
            elapsed = time.monotonic() - started
            if elapsed > self._period_seconds:
                logfire.warn(
                    "ingestion.arrivals.cycle_overrun",
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
        producer = ArrivalsProducer(tfl_client=tfl, kafka_producer=kafka)
        await producer.run_forever()


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.producers.arrivals``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
