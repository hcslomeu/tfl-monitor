"""LlamaIndex retrieval over the pgvector tfl-strategy-docs table.

A single ``VectorStoreIndex`` backs every query; ``doc_id`` becomes a
metadata filter rather than a Pinecone namespace, so targeting one
document is just an extra ``WHERE`` clause. Page sentinel ``-1`` maps to
``None`` so the LLM never sees a sentinel page number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import logfire
from pydantic import BaseModel, ConfigDict

from rag.config import RagSettings
from rag.upsert import PAGE_UNKNOWN_SENTINEL
from rag.vectorstore import build_embedding, build_vector_store

if TYPE_CHECKING:
    from llama_index.core import VectorStoreIndex

# Canonical corpus doc_ids (one TfL strategy PDF each). Used to type the
# agent tool's optional doc_id argument.
DOC_IDS: tuple[str, ...] = (
    "business_plan_2026",
    "mts_delivery_2024_25",
    "bus_action_plan",
    "vision_zero",
    "cycling_action_plan",
    "travel_in_london_2025",
)
DEFAULT_TOP_K = 5


class TflDocSnippet(BaseModel):
    """Flat retrieval hit returned to the agent."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_title: str
    section_title: str
    page_start: int | None
    page_end: int | None
    text: str
    score: float
    resolved_url: str


def build_retriever(*, settings: RagSettings) -> VectorStoreIndex:
    """Build the pgvector-backed LlamaIndex over the strategy corpus.

    The index is lazy: it does not connect to Postgres until the first
    query, so construction succeeds even before the table is populated.

    Args:
        settings: RAG settings (pgvector DSN + Bedrock embedding config).

    Returns:
        A ``VectorStoreIndex`` ready for ``as_retriever``.
    """
    from llama_index.core import VectorStoreIndex  # noqa: PLC0415

    vector_store = build_vector_store(settings)
    embed_model = build_embedding(settings)
    return VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)


async def retrieve(
    index: VectorStoreIndex,
    *,
    query: str,
    doc_id: str | None,
    top_k: int,
) -> list[TflDocSnippet]:
    """Retrieve top-``k`` snippets, optionally scoped to one ``doc_id``.

    Args:
        index: Index from :func:`build_retriever`.
        query: Natural-language search query.
        doc_id: Restrict search to one document via a metadata filter.
            ``None`` searches the whole corpus.
        top_k: Maximum number of snippets to return.

    Returns:
        Snippets sorted by score descending; an empty list when the
        store is unreachable (graceful degradation — the agent can still
        answer from the SQL tools).
    """
    filters = None
    if doc_id is not None:
        from llama_index.core.vector_stores import (  # noqa: PLC0415
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )

        filters = MetadataFilters(
            filters=[MetadataFilter(key="doc_id", value=doc_id, operator=FilterOperator.EQ)]
        )

    try:
        retriever = index.as_retriever(similarity_top_k=top_k, filters=filters)
        nodes = await retriever.aretrieve(query)
    except Exception as exc:  # noqa: BLE001 - retrieval must not crash the agent
        # Log the exception class only — the message can embed DSN/payload data.
        logfire.warning("agent.rag.retrieve_failed", doc_id=doc_id, error_type=type(exc).__name__)
        return []

    snippets = [_to_snippet(node) for node in nodes]
    snippets.sort(key=lambda hit: hit.score, reverse=True)
    return snippets[:top_k]


def _normalise_page(value: Any) -> int | None:
    """Map the ``-1`` page sentinel (and ``None``) to ``None``.

    Non-numeric metadata coerces to ``None`` rather than raising.
    """
    if value is None or value == PAGE_UNKNOWN_SENTINEL:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_snippet(node: Any) -> TflDocSnippet:
    """Coerce a LlamaIndex ``NodeWithScore`` into ``TflDocSnippet``."""
    meta_source = getattr(node, "metadata", None)
    if not meta_source:
        inner = getattr(node, "node", None)
        meta_source = getattr(inner, "metadata", None) if inner is not None else None
    meta: dict[str, Any] = dict(meta_source or {})

    text = meta.get("text") or getattr(node, "text", None)
    if not text:
        inner = getattr(node, "node", None)
        text = getattr(inner, "text", "") if inner is not None else ""

    raw_score = getattr(node, "score", None)
    score = float(raw_score) if raw_score is not None else 0.0

    return TflDocSnippet(
        doc_id=str(meta.get("doc_id") or ""),
        doc_title=str(meta.get("doc_title") or ""),
        section_title=str(meta.get("section_title") or ""),
        page_start=_normalise_page(meta.get("page_start")),
        page_end=_normalise_page(meta.get("page_end")),
        text=str(text or ""),
        score=score,
        resolved_url=str(meta.get("resolved_url") or ""),
    )
