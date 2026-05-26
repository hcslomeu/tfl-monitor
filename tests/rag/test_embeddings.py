"""Unit tests for :mod:`rag.embeddings` (Bedrock Titan v2)."""

from __future__ import annotations

import json
from typing import Any

from rag.embeddings import TitanEmbedding


class _FakeBody:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw


class _FakeBedrock:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._vector = vector or [0.1, 0.2, 0.3]

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"modelId": kwargs["modelId"], "body": json.loads(kwargs["body"])})
        return {"body": _FakeBody({"embedding": self._vector})}


def _embedding(client: _FakeBedrock) -> TitanEmbedding:
    return TitanEmbedding(
        model_name="amazon.titan-embed-text-v2:0",
        region="eu-west-2",
        dimensions=1024,
        client=client,
    )


def test_get_text_embedding_returns_vector_and_sends_titan_params() -> None:
    client = _FakeBedrock(vector=[0.5, 0.6])
    embed = _embedding(client)

    vector = embed.get_text_embedding("hello")

    assert vector == [0.5, 0.6]
    assert client.calls[0]["modelId"] == "amazon.titan-embed-text-v2:0"
    assert client.calls[0]["body"] == {
        "inputText": "hello",
        "dimensions": 1024,
        "normalize": True,
    }


def test_get_query_embedding_uses_same_call() -> None:
    client = _FakeBedrock(vector=[1.0])
    embed = _embedding(client)

    assert embed.get_query_embedding("q") == [1.0]
    assert client.calls[0]["body"]["inputText"] == "q"


def test_get_text_embedding_batch_embeds_each_input() -> None:
    client = _FakeBedrock(vector=[0.9])
    embed = _embedding(client)

    vectors = embed.get_text_embedding_batch(["a", "b", "c"])

    assert vectors == [[0.9], [0.9], [0.9]]
    assert [call["body"]["inputText"] for call in client.calls] == ["a", "b", "c"]


def test_class_name() -> None:
    assert TitanEmbedding.class_name() == "TitanEmbedding"
