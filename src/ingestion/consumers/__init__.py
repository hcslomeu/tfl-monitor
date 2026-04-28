"""Kafka → Postgres consumers for TfL ingestion."""

from ingestion.consumers.event_consumer import (
    DEFAULT_LAG_REFRESH_MESSAGES,
    DEFAULT_LAG_REFRESH_SECONDS,
    RawEventConsumer,
)
from ingestion.consumers.kafka import KafkaConsumerError, KafkaEventConsumer
from ingestion.consumers.postgres import (
    ALLOWED_RAW_TABLES,
    INSERT_RAW_EVENT_SQL_TEMPLATE,
    RawEventWriter,
)

__all__ = [
    "ALLOWED_RAW_TABLES",
    "DEFAULT_LAG_REFRESH_MESSAGES",
    "DEFAULT_LAG_REFRESH_SECONDS",
    "INSERT_RAW_EVENT_SQL_TEMPLATE",
    "KafkaConsumerError",
    "KafkaEventConsumer",
    "RawEventConsumer",
    "RawEventWriter",
]
