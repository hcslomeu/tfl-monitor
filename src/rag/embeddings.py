"""Bedrock Titan v2 text embeddings as a LlamaIndex embedding model.

``amazon.titan-embed-text-v2:0`` embeds a single text per
``invoke_model`` call, so batches loop. boto3 reads AWS credentials from
the standard chain — the same keys that drive the Bedrock chat model —
so no API key is required.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr


class TitanEmbedding(BaseEmbedding):
    """LlamaIndex embedding backed by Bedrock Titan Text Embeddings v2."""

    # Defaults only satisfy BaseEmbedding's required-field validation during
    # super().__init__; the real values are assigned immediately after.
    region: str = ""
    dimensions: int = 0
    normalize: bool = True

    _client: Any = PrivateAttr(default=None)

    def __init__(
        self,
        *,
        model_name: str,
        region: str,
        dimensions: int,
        normalize: bool = True,
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model_name=model_name, **kwargs)
        self.region = region
        self.dimensions = dimensions
        self.normalize = normalize
        self._client = client

    @classmethod
    def class_name(cls) -> str:
        return "TitanEmbedding"

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def _embed(self, text: str) -> list[float]:
        body = json.dumps(
            {"inputText": text, "dimensions": self.dimensions, "normalize": self.normalize}
        )
        response = self.client.invoke_model(
            modelId=self.model_name,
            body=body,
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read())
        return [float(value) for value in payload["embedding"]]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await asyncio.to_thread(self._embed, query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed, text)
