"""Unit tests for :mod:`rag.embed`."""

from __future__ import annotations

import httpx
import pytest
from openai import RateLimitError

from rag.embed import EmbeddingClientError, embed_texts


class _FakeEmbeddingItem:
    def __init__(self, vector: list[float]) -> None:
        self.embedding = vector


class _FakeEmbeddingResponse:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.data = [_FakeEmbeddingItem(v) for v in vectors]


class _FakeEmbeddings:
    def __init__(self, error_sequence: list[Exception | None]) -> None:
        self.calls: list[list[str]] = []
        self._errors = list(error_sequence)

    async def create(self, *, model: str, input: list[str]) -> _FakeEmbeddingResponse:
        del model
        self.calls.append(list(input))
        if self._errors:
            err = self._errors.pop(0)
            if err is not None:
                raise err
        return _FakeEmbeddingResponse([[float(i)] * 4 for i in range(len(input))])


class _FakeOpenAI:
    def __init__(self, error_sequence: list[Exception | None] | None = None) -> None:
        self.embeddings = _FakeEmbeddings(error_sequence or [])


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(429, request=request, text="rate limit")
    return RateLimitError("rate limit", response=response, body=None)


async def test_embed_texts_batches_at_100() -> None:
    client = _FakeOpenAI()
    texts = [f"chunk {i}" for i in range(150)]
    vectors = await embed_texts(texts, client=client, model="text-embedding-3-small")
    assert len(vectors) == 150
    assert [len(call) for call in client.embeddings.calls] == [100, 50]


async def test_embed_texts_retries_on_rate_limit() -> None:
    client = _FakeOpenAI(error_sequence=[_rate_limit_error()])
    texts = ["a", "b", "c"]
    vectors = await embed_texts(texts, client=client, model="text-embedding-3-small")
    assert len(vectors) == 3
    assert len(client.embeddings.calls) == 2  # one retry


async def test_embed_texts_raises_after_exhaustion() -> None:
    client = _FakeOpenAI(error_sequence=[_rate_limit_error(), _rate_limit_error()])
    with pytest.raises(EmbeddingClientError) as excinfo:
        await embed_texts(
            ["a"],
            client=client,
            model="text-embedding-3-small",
            max_attempts=2,
        )
    assert "after 2 attempts" in str(excinfo.value)


async def test_embed_texts_rejects_invalid_inputs() -> None:
    client = _FakeOpenAI()
    with pytest.raises(ValueError):
        await embed_texts(
            ["a"],
            client=client,
            model="text-embedding-3-small",
            batch_size=0,
        )
    with pytest.raises(ValueError):
        await embed_texts(
            ["a"],
            client=client,
            model="text-embedding-3-small",
            max_attempts=0,
        )
