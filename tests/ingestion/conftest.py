"""Shared fixtures and HTTP mock helpers for ingestion tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tfl"


def _load(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
def line_status_tube_fixture() -> list[dict[str, Any]]:
    return _load("line_status_tube.json")


@pytest.fixture
def line_status_multi_mode_fixture() -> list[dict[str, Any]]:
    return _load("line_status_multi_mode.json")


@pytest.fixture
def arrivals_oxford_circus_fixture() -> list[dict[str, Any]]:
    return _load("arrivals_oxford_circus.json")


@pytest.fixture
def disruptions_tube_fixture() -> list[dict[str, Any]]:
    return _load("disruptions_tube.json")


ResponseFactory = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def make_transport() -> Callable[[ResponseFactory], httpx.MockTransport]:
    """Return a factory that wires a response handler to ``httpx.MockTransport``."""

    def _make(handler: ResponseFactory) -> httpx.MockTransport:
        return httpx.MockTransport(handler)

    return _make


@pytest.fixture
def script_responses() -> Callable[[list[httpx.Response]], ResponseFactory]:
    """Return a handler factory that replays a fixed list of responses in order."""

    def _factory(responses: list[httpx.Response]) -> ResponseFactory:
        queue: Iterator[httpx.Response] = iter(responses)

        def _handler(_request: httpx.Request) -> httpx.Response:
            try:
                return next(queue)
            except StopIteration as exc:  # pragma: no cover - defensive
                raise AssertionError(
                    "MockTransport received more requests than scripted responses"
                ) from exc

        return _handler

    return _factory
