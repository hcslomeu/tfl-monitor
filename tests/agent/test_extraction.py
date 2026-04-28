"""Unit tests for the Pydantic AI line-id normaliser."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from api.agent import extraction
from api.agent.extraction import _normaliser, normalise_line_id


@pytest.fixture(autouse=True)
def _stub_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pydantic AI's Anthropic provider validates the env key at construction.

    The real LLM never runs in this suite (we override the model), but the
    initial ``Agent("anthropic:...")`` constructor still needs *something*.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.mark.asyncio
async def test_canonical_pass_through_skips_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    """A canonical token short-circuits and never calls the LLM."""

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("LLM should not run for canonical input")

    monkeypatch.setattr(extraction, "_normaliser", _explode)

    assert await normalise_line_id("piccadilly") == "piccadilly"
    assert await normalise_line_id("elizabeth") == "elizabeth"


@pytest.mark.asyncio
async def test_lizzy_slang_maps_to_elizabeth() -> None:
    """Free-text slang is normalised via the overridden Haiku model."""
    agent = _normaliser()
    with agent.override(model=TestModel(custom_output_args={"line_id": "elizabeth"})):
        assert await normalise_line_id("Lizzy line") == "elizabeth"


@pytest.mark.asyncio
async def test_typo_maps_to_canonical() -> None:
    """A typo is rescued by the LLM."""
    agent = _normaliser()
    with agent.override(model=TestModel(custom_output_args={"line_id": "piccadilly"})):
        assert await normalise_line_id("piccadily") == "piccadilly"


@pytest.mark.asyncio
async def test_nonsense_returns_none() -> None:
    """When the LLM raises, the boundary returns ``None``."""

    class _BoomModel(TestModel):
        async def request(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("no match")

    agent = _normaliser()
    with agent.override(model=_BoomModel()):
        assert await normalise_line_id("my favourite stop") is None
