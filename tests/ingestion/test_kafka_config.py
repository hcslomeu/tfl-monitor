"""Unit tests for ``ingestion.kafka_config.build_aiokafka_security_config``."""

from __future__ import annotations

import ssl

import pytest

from ingestion.kafka_config import build_aiokafka_security_config


def test_returns_empty_dict_when_protocol_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAFKA_SECURITY_PROTOCOL", raising=False)
    assert build_aiokafka_security_config() == {}


def test_returns_empty_dict_when_protocol_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    assert build_aiokafka_security_config() == {}


def test_returns_ssl_only_kwargs_when_protocol_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SSL")
    monkeypatch.delenv("KAFKA_SASL_MECHANISM", raising=False)
    monkeypatch.delenv("KAFKA_SASL_USERNAME", raising=False)
    monkeypatch.delenv("KAFKA_SASL_PASSWORD", raising=False)

    config = build_aiokafka_security_config()

    assert config["security_protocol"] == "SSL"
    assert isinstance(config["ssl_context"], ssl.SSLContext)
    assert "sasl_mechanism" not in config
    assert "sasl_plain_username" not in config
    assert "sasl_plain_password" not in config


def test_returns_full_sasl_ssl_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    monkeypatch.setenv("KAFKA_SASL_MECHANISM", "SCRAM-SHA-256")
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "redpanda-user")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "redpanda-secret")

    config = build_aiokafka_security_config()

    assert config["security_protocol"] == "SASL_SSL"
    assert config["sasl_mechanism"] == "SCRAM-SHA-256"
    assert config["sasl_plain_username"] == "redpanda-user"
    assert config["sasl_plain_password"] == "redpanda-secret"
    assert isinstance(config["ssl_context"], ssl.SSLContext)


def test_sasl_plaintext_skips_ssl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
    monkeypatch.setenv("KAFKA_SASL_MECHANISM", "SCRAM-SHA-256")
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "u")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "p")

    config = build_aiokafka_security_config()

    assert config["security_protocol"] == "SASL_PLAINTEXT"
    assert config["sasl_mechanism"] == "SCRAM-SHA-256"
    assert config["sasl_plain_username"] == "u"
    assert config["sasl_plain_password"] == "p"
    assert "ssl_context" not in config


def test_protocol_is_uppercased(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "sasl_ssl")
    monkeypatch.setenv("KAFKA_SASL_MECHANISM", "SCRAM-SHA-256")
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "u")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "p")

    config = build_aiokafka_security_config()

    assert config["security_protocol"] == "SASL_SSL"


@pytest.mark.parametrize(
    "missing_var",
    ["KAFKA_SASL_MECHANISM", "KAFKA_SASL_USERNAME", "KAFKA_SASL_PASSWORD"],
)
def test_raises_when_sasl_credentials_missing(
    monkeypatch: pytest.MonkeyPatch, missing_var: str
) -> None:
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    for name, value in (
        ("KAFKA_SASL_MECHANISM", "SCRAM-SHA-256"),
        ("KAFKA_SASL_USERNAME", "u"),
        ("KAFKA_SASL_PASSWORD", "p"),
    ):
        if name == missing_var:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as excinfo:
        build_aiokafka_security_config()

    assert missing_var in str(excinfo.value)
