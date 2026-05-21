"""Single-process entrypoint running every TfL producer concurrently.

Collapses the three per-topic producer entrypoints (``line_status``,
``arrivals``, ``disruptions``) into one ``asyncio.gather`` so the
shared Lightsail box only pays the cost of one Python process, one
``TflClient``, and one ``KafkaEventProducer`` instead of three.

The per-topic ``main`` entrypoints remain available for local dev and
backwards compatibility.
"""

from __future__ import annotations

import asyncio
import os
from typing import NoReturn

import logfire

from ingestion.kafka_config import build_aiokafka_security_config
from ingestion.observability import configure_logfire
from ingestion.producers.arrivals import ArrivalsProducer
from ingestion.producers.disruptions import DisruptionsProducer
from ingestion.producers.kafka import KafkaEventProducer
from ingestion.producers.line_status import LineStatusProducer
from ingestion.tfl_client import TflClient


async def _amain() -> NoReturn:
    configure_logfire()

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is required")

    # Empty dict on plaintext local Redpanda; SASL_SSL kwargs on Redpanda Cloud.
    aiokafka_extra_config = build_aiokafka_security_config()

    async with (
        TflClient.from_env() as tfl,
        KafkaEventProducer(
            bootstrap_servers=bootstrap,
            aiokafka_extra_config=aiokafka_extra_config,
        ) as kafka,
    ):
        line_status = LineStatusProducer(tfl_client=tfl, kafka_producer=kafka)
        arrivals = ArrivalsProducer(tfl_client=tfl, kafka_producer=kafka)
        disruptions = DisruptionsProducer(tfl_client=tfl, kafka_producer=kafka)
        logfire.info("ingestion.run_producers.start", count=3)
        # TaskGroup (Python 3.11+) propagates the first failure as an
        # ExceptionGroup and cancels the surviving producers, so the
        # box's process supervisor (Docker restart=unless-stopped)
        # restarts the whole bundle cleanly.
        async with asyncio.TaskGroup() as tg:
            tg.create_task(line_status.run_forever())
            tg.create_task(arrivals.run_forever())
            tg.create_task(disruptions.run_forever())

    raise AssertionError("run_forever loops never return")


def main() -> None:
    """Module entrypoint used by ``python -m ingestion.run_producers``."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
