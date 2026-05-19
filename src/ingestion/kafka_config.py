"""Build ``aiokafka`` security keyword arguments from environment variables.

Reads ``KAFKA_SECURITY_PROTOCOL`` / ``KAFKA_SASL_MECHANISM`` /
``KAFKA_SASL_USERNAME`` / ``KAFKA_SASL_PASSWORD`` and returns a dict that
is forwarded as ``**kwargs`` to ``AIOKafkaProducer`` and
``AIOKafkaConsumer`` constructors.

Local dev (plaintext Redpanda inside ``docker-compose.yml``) keeps
working with no extra environment configuration: when
``KAFKA_SECURITY_PROTOCOL`` is unset or ``PLAINTEXT`` the function
returns an empty dict so the wrappers fall back to ``aiokafka``
defaults.

Production (Redpanda Cloud Serverless, SASL/SCRAM over TLS) needs the
full set: ``KAFKA_SECURITY_PROTOCOL=SASL_SSL`` +
``KAFKA_SASL_MECHANISM=SCRAM-SHA-256`` + ``KAFKA_SASL_USERNAME`` +
``KAFKA_SASL_PASSWORD``. Missing values fail loudly with
``SystemExit`` rather than silently falling back to a plaintext
connection that the cloud broker would reject anyway.
"""

from __future__ import annotations

import os
import ssl
from typing import Any

__all__ = ["build_aiokafka_security_config"]

_PLAINTEXT_PROTOCOLS = frozenset({"", "PLAINTEXT"})
_SASL_PROTOCOLS = frozenset({"SASL_PLAINTEXT", "SASL_SSL"})
_TLS_PROTOCOLS = frozenset({"SSL", "SASL_SSL"})
_SUPPORTED_PROTOCOLS = frozenset({"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"})


def build_aiokafka_security_config() -> dict[str, Any]:
    """Return aiokafka ``security_protocol`` / SASL / SSL kwargs from env.

    Returns:
        Empty dict when ``KAFKA_SECURITY_PROTOCOL`` is unset or
        ``PLAINTEXT``. Otherwise a dict with ``security_protocol`` plus
        the SASL credentials (when the protocol uses SASL) and an
        ``ssl_context`` built from the system CA bundle (when the
        protocol uses TLS).

    Raises:
        SystemExit: When ``KAFKA_SECURITY_PROTOCOL`` is set to an
            unsupported value, or when SASL is requested but any of
            ``KAFKA_SASL_MECHANISM`` / ``KAFKA_SASL_USERNAME`` /
            ``KAFKA_SASL_PASSWORD`` is missing.
    """
    # `.strip()` tolerates accidental leading / trailing whitespace introduced
    # by hand-edited `.env` files; `.upper()` lets operators set the protocol
    # in either case without surprising the supported-set check below.
    protocol = os.environ.get("KAFKA_SECURITY_PROTOCOL", "").strip().upper()
    if protocol in _PLAINTEXT_PROTOCOLS:
        return {}

    # Validate upfront so a typo (e.g. ``SALS_SSL``) fails with a clear
    # configuration error rather than a generic aiokafka bootstrap failure
    # several layers deeper.
    if protocol not in _SUPPORTED_PROTOCOLS:
        supported = ", ".join(sorted(_SUPPORTED_PROTOCOLS))
        raise SystemExit(
            f"KAFKA_SECURITY_PROTOCOL={protocol!r} is not supported; expected one of: {supported}"
        )

    config: dict[str, Any] = {"security_protocol": protocol}

    if protocol in _SASL_PROTOCOLS:
        # Strip whitespace and uppercase the mechanism for the same reason as
        # the protocol — Kafka mechanisms (PLAIN, SCRAM-SHA-256, SCRAM-SHA-512,
        # GSSAPI, OAUTHBEARER) are uppercase by convention.
        mechanism = os.environ.get("KAFKA_SASL_MECHANISM", "").strip().upper()
        username = os.environ.get("KAFKA_SASL_USERNAME", "")
        password = os.environ.get("KAFKA_SASL_PASSWORD", "")
        missing = [
            name
            for name, value in (
                ("KAFKA_SASL_MECHANISM", mechanism),
                ("KAFKA_SASL_USERNAME", username),
                ("KAFKA_SASL_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise SystemExit(f"KAFKA_SECURITY_PROTOCOL={protocol} requires {' + '.join(missing)}")
        config["sasl_mechanism"] = mechanism
        config["sasl_plain_username"] = username
        config["sasl_plain_password"] = password

    if protocol in _TLS_PROTOCOLS:
        config["ssl_context"] = ssl.create_default_context()

    return config
