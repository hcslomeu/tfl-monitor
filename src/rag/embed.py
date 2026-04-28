"""Async OpenAI embeddings with batching and 429-aware retry.

Mirrors the retry shape of :mod:`ingestion.tfl_client.retry`: bounded
attempts with exponential backoff (capped at 10 s). Distinct from the
TfL retry helper because the OpenAI exception hierarchy is different
and a shared abstraction would be premature (CLAUDE.md §"Principle #1"
rule 4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

import logfire
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 0.5
_MAX_BACKOFF_SECONDS = 10.0


class EmbeddingClientError(RuntimeError):
    """Raised when every embedding attempt for a batch fails."""


class _EmbeddingsAPI(Protocol):
    async def create(self, *, model: str, input: list[str]) -> Any: ...


class _AsyncOpenAILike(Protocol):
    embeddings: _EmbeddingsAPI


def _exponential_backoff(attempt: int) -> float:
    delay: float = _BASE_BACKOFF_SECONDS * (2**attempt)
    return min(delay, _MAX_BACKOFF_SECONDS)


async def embed_texts(
    texts: Sequence[str],
    *,
    client: AsyncOpenAI | _AsyncOpenAILike,
    model: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> list[list[float]]:
    """Embed ``texts`` in batches; return one vector per input."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        with logfire.span(
            "rag.embed",
            model=model,
            n_inputs=len(batch),
            batch_index=start // batch_size,
        ):
            response = await _embed_batch_with_retry(
                batch,
                client=client,
                model=model,
                max_attempts=max_attempts,
            )
        vectors.extend([list(item.embedding) for item in response.data])
    return vectors


async def _embed_batch_with_retry(
    batch: list[str],
    *,
    client: AsyncOpenAI | _AsyncOpenAILike,
    model: str,
    max_attempts: int,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await client.embeddings.create(model=model, input=batch)
        except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            await asyncio.sleep(_exponential_backoff(attempt))
    raise EmbeddingClientError(f"OpenAI embed failed after {max_attempts} attempts: {last_exc!r}")
