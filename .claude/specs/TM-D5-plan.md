# TM-D5 — Plan (Phase 2)

Implementation plan for **TM-D5: LangGraph agent (SQL + RAG +
Pydantic AI)** — Linear `TM-18`. Built from
`.claude/specs/TM-D5-research.md`. Every open question (§15 of the
research file) is resolved here. Structure mirrors
`TM-D3-plan.md`.

## 1. Charter (locked)

Replace the two TM-D5-keyed 501 stubs with a streaming LangGraph
agent and a thread-history endpoint:

| Method | Path | Backed by |
|---|---|---|
| POST | `/api/v1/chat/stream` | LangGraph `create_react_agent` over Sonnet + 5 tools (4 SQL + 1 RAG); Pydantic AI Haiku normaliser inside the reliability tool; sse-starlette `EventSourceResponse`. |
| GET | `/api/v1/chat/{thread_id}/history` | Single `SELECT … FROM analytics.chat_messages` via the existing `AsyncConnectionPool`. |

**One PR** for both endpoints.

### Files added

- `src/api/agent/__init__.py`
- `src/api/agent/graph.py` — agent compile + cache.
- `src/api/agent/tools.py` — 5 LangChain `@tool`s + Pydantic input schemas.
- `src/api/agent/extraction.py` — Pydantic AI line-id normaliser.
- `src/api/agent/prompts.py` — `SYSTEM_PROMPT` constant.
- `src/api/agent/streaming.py` — `_frame_from`, the SSE projection helper.
- `src/api/agent/history.py` — `analytics.chat_messages` CRUD helpers.
- `contracts/sql/004_chat.sql` — DDL for `analytics.chat_messages`.
- `tests/agent/{__init__,conftest}.py`
- `tests/agent/{test_extraction,test_sql_tools,test_rag_tool,test_graph_compile}.py`
- `tests/api/{test_chat_history,test_chat_stream}.py`
- `tests/integration/{test_chat_history,test_chat_stream,test_chat_history_after_stream}.py`

### Files modified

- `pyproject.toml` — add `langchain-anthropic>=0.3` and
  `llama-index-vector-stores-pinecone>=0.4` to `[project].dependencies`.
- `uv.lock` — regenerated (`uv lock`).
- `src/api/main.py` — lifespan compiles + caches the agent in
  `app.state.agent`; `post_chat_stream` returns `EventSourceResponse`;
  `get_chat_history` queries `analytics.chat_messages`.
- `tests/api/test_stubs.py` — drop the two TM-D5 rows from
  `STUB_ROUTES`.
- `PROGRESS.md` — TM-D5 row flipped to ✅.

### Files untouched

- `contracts/openapi.yaml` (frozen).
- `contracts/schemas/*` (Kafka tier).
- `dbt/`, `web/`, `src/ingestion/`, `src/rag/`, `airflow/`,
  `Makefile`, `docker-compose.yml`, `.env.example` (every required
  env var is already declared).

### Estimated diff size

- Source: ~430 LoC (graph 80, tools 130, extraction 50, streaming 80,
  history 40, prompts 30, main.py edits 20).
- Tests: ~520 LoC (5 unit files × ~80 LoC, 3 integration files × ~60 LoC,
  conftest 30).
- DDL: ~25 LoC.
- Total ~1000 LoC. Above the implicit 600-LoC threshold mentioned in
  TM-D3 plan §1, but warranted by scope (5 tools + SSE handler +
  Pydantic AI extractor + new persistence layer + 8 test files).
  Split mitigation: see §7 below.

## 2. Decisions (Phase 2 lock)

Every research §15 question gets an answer. No "TBD".

| # | Question | Decision |
|---|---|---|
| 1 | Graph topology | `create_react_agent` (research §3 Option A). Single Sonnet loop, five tools. |
| 2 | Models | Sonnet for the loop (`anthropic:claude-3-5-sonnet-latest` via `langchain_anthropic.ChatAnthropic`). Haiku reserved for the Pydantic AI line-id normaliser only (`anthropic:claude-3-5-haiku-latest`). |
| 3 | SQL tools call path | Direct in-process call to TM-D2/D3 fetchers from `src/api/db.py`. No HTTP self-call. Tools share the existing `app.state.db_pool`. |
| 4 | RAG retrieval | Per-`doc_id` namespace fan-out (`asyncio.gather` across the three `doc_id`s) when the LLM does not pass `doc_id`; single-namespace query when it does. Top-k = 5 per leg, no rerank, no score threshold. |
| 5 | Pydantic AI scope | Line-id normaliser only. Used inside `query_line_reliability` to map *"Lizzy line"* → `elizabeth` before the SQL fires, when the LLM-supplied `line_id` is not in the canonical literal set. Skipped for graph routing. |
| 6 | LangGraph checkpointer | `langgraph.checkpoint.memory.InMemorySaver`. No new persistence dep. Restart loses in-flight working memory; `/history` survives via the SQL log (decision #7). |
| 7 | Chat history storage | New `analytics.chat_messages` table (DDL in `contracts/sql/004_chat.sql`). One INSERT per user turn (before stream starts) + one INSERT per assistant turn (after stream ends). |
| 8 | Cross-track edit on `contracts/sql/` | In-scope. Additive, non-breaking schema; ADR 002 §"Consequences" allows contract changes when justified; we do not need a new ADR because the chat-messages table is API-owned (no Kafka or dbt consumer). PR body declares the cross-track touch explicitly. |
| 9 | Graceful degradation | Lifespan computes `app.state.agent`. The agent is `None` if **any** of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `PINECONE_API_KEY` is missing; `/chat/stream` returns `503` problem in that case. `/chat/{tid}/history` is independent — only needs `DATABASE_URL`; returns `503` problem if the pool is missing. |
| 10 | Module layout | New `src/api/agent/` package: `graph.py`, `tools.py`, `extraction.py`, `prompts.py`, `streaming.py`, `history.py`. Flat `src/api/main.py` keeps ownership of the FastAPI route bodies and the lifespan. |
| 11 | Empty `/history` thread | Returns `404 application/problem+json` with detail `"No history for thread {thread_id}"` when zero rows match. (Empty thread = thread never seen by `/chat/stream`.) |
| 12 | SSE `ping` | sse-starlette default `ping=15`. Document at TM-A5 / TM-E4 that Vercel may need a tighter value (~9 s) for production. No tweak in this PR. |
| 13 | Tool catalogue | Five tools, locked: `query_tube_status`, `query_line_reliability`, `query_recent_disruptions`, `query_bus_punctuality`, `search_tfl_docs`. All have Pydantic-typed inputs validated by Pydantic v2 / `Field` constraints. |
| 14 | System prompt | Single string constant in `src/api/agent/prompts.py`, ~600 chars, mentions today's date (filled at request time via `prompt=f"...{date.today().isoformat()}..."` re-bound per call), instructs the model to cite RAG sources by `doc_title` + page, and to surface the bus proxy caveat. |
| 15 | Bandit | `uv run bandit -r src --severity-level high` zero findings. |

### Tool catalogue (locked)

```python
# src/api/agent/tools.py — locked input schemas

class LineReliabilityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: str = Field(min_length=1, max_length=64)
    window_days: int = Field(default=7, ge=1, le=90)


class RecentDisruptionsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=10, ge=1, le=200)
    mode: Mode | None = None


class BusPunctualityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stop_id: str = Field(min_length=1, max_length=64)


class TflDocSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=512)
    doc_id: Literal["tfl_business_plan", "mts_2018", "tfl_annual_report"] | None = None
    top_k: int = Field(default=5, ge=1, le=20)


# query_tube_status takes no arguments.
```

`Mode` reused from `src/api/schemas.py` (the existing OpenAPI literal).

## 3. Acceptance criteria (locked)

Functional:

- [ ] `POST /api/v1/chat/stream` accepts the OpenAPI-declared
  `ChatRequest` (`thread_id: str`, `message: str` 1–4000 chars).
  FastAPI's Pydantic body validator emits `422` for malformed input
  (consistent with TM-D2/D3 422 behaviour).
- [ ] On `200`, the response is `Content-Type: text/event-stream`;
  each `data:` frame is JSON `{"type": "token"|"tool"|"end", "content": <str>}`;
  the stream always ends with one `{"type":"end","content":""}` frame
  (or `"content":"error"` on a generator-internal failure).
- [ ] At least one `token` frame is emitted for any non-trivial
  prompt; `tool` frames are emitted when the agent calls a tool;
  empty token frames are filtered out (research §14.11).
- [ ] User message is persisted to `analytics.chat_messages`
  *before* the first SSE frame is yielded; assistant message is
  persisted *after* the final `end` frame.
- [ ] `app.state.agent is None` (any of the three API keys missing)
  → `503 application/problem+json` with detail
  `"Chat agent is not configured"`.
- [ ] `app.state.db_pool is None` → `503 application/problem+json`
  with detail `"Database pool is not available"` (mirrors TM-D2/D3).
- [ ] `GET /api/v1/chat/{thread_id}/history` returns `ChatMessage[]`
  ordered by `created_at ASC` and tie-broken by `id ASC`.
- [ ] Empty thread → `404 application/problem+json` with detail
  `"No history for thread {thread_id}"`.
- [ ] `app.state.db_pool is None` → `503` problem (same as above).

Non-functional:

- [ ] All SQL parameterised. `analytics.chat_messages` reads/writes
  use named `%(name)s` placeholders.
- [ ] All five LangGraph tools have **Pydantic-typed inputs**
  (`extra="forbid"`); the model cannot smuggle a SQL fragment
  past the type system (CLAUDE.md §"Security-first").
- [ ] No free-form SQL exposed to the LLM. No `exec_sql`-style tool.
- [ ] CORS allowlist preserved.
- [ ] OpenAPI bidirectional drift checks in
  `tests/api/test_stubs.py` stay green; the two TM-D5 rows are
  dropped from `STUB_ROUTES`.
- [ ] The agent is compiled **once** in the lifespan and cached on
  `app.state.agent`; subsequent requests share the compiled graph.
- [ ] LangGraph uses `InMemorySaver`; restart loses in-flight thread
  state.
- [ ] LangSmith auto-instrumentation works without code changes (env
  vars only); Logfire instruments the SSE request span via the
  existing `instrument_fastapi`.
- [ ] sse-starlette `ping=15`, default `send_timeout`. The generator
  honours `await request.is_disconnected()` and re-raises
  `asyncio.CancelledError`.
- [ ] `pyproject.toml` adds exactly two deps:
  `langchain-anthropic>=0.3`, `llama-index-vector-stores-pinecone>=0.4`.
  `uv.lock` regenerated.
- [ ] `contracts/sql/004_chat.sql` ships idempotent DDL
  (`CREATE SCHEMA IF NOT EXISTS analytics`,
  `CREATE TABLE IF NOT EXISTS …`, `CREATE INDEX IF NOT EXISTS …`).
- [ ] `tests/test_health.py`, `tests/api/test_status_*`,
  `tests/api/test_reliability.py`, `tests/api/test_disruptions_recent.py`,
  `tests/api/test_bus_punctuality.py`, and the rest of the existing
  default suite keep passing.
- [ ] New unit tests: `tests/agent/test_{extraction,sql_tools,rag_tool,graph_compile}.py`,
  `tests/api/test_chat_history.py`, `tests/api/test_chat_stream.py`.
- [ ] New integration tests: `tests/integration/test_chat_history.py`,
  `tests/integration/test_chat_stream.py`,
  `tests/integration/test_chat_history_after_stream.py`. The stream
  ones gate on `DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `PINECONE_API_KEY` (skip if any unset) and are also marked
  `@pytest.mark.integration` so they stay out of the default `addopts`.
- [ ] `uv run task lint` (ruff + ruff format + mypy strict) green.
- [ ] `uv run task test` (default, hermetic) green.
- [ ] `uv run bandit -r src --severity-level high` reports zero
  findings.
- [ ] `make check` green end-to-end.
- [ ] `PROGRESS.md` TM-D5 row flipped to ✅ with completion date.
- [ ] PR title `feat(api): TM-D5 LangGraph agent (SQL + RAG)` referencing
  `TM-18`. PR body lists deliverables, declares the
  `contracts/sql/004_chat.sql` cross-track touch with rationale, and
  closes Linear `TM-18`.

## 4. What we are NOT doing

Out of scope for this WP — pushed to other WPs or the backlog.

- **Multi-turn chat UI** → TM-E3. The frontend wires this stream;
  TM-D5 ships the contract and one curl-driven smoke is enough.
- **Cross-thread memory** (long-term recall, summarisation,
  "remember my preferences"). LangGraph supports it via the Store
  API; we ship without. Each `thread_id` is independent.
- **Voice / audio** input or output.
- **Streaming retry / backoff beyond `EventSourceResponse`'s built-ins.**
  If the LLM call dies mid-stream, the generator emits a final
  `end` frame with `content="error"` and the client decides whether
  to retry. No exponential-backoff retry loop in the handler.
- **Custom prompt-injection detector.** TfL strategy PDFs are
  trusted publications; the system prompt instructs the model to
  ignore instructions inside cited content. If the corpus ever
  expands to user-uploaded PDFs, a detector becomes required;
  capture as an ADR then.
- **Output guardrails layer** (PII redaction, profanity filter).
  Anthropic's policy enforcement is sufficient for portfolio scope.
- **Haiku-routed two-model graph** (research §3 Option B). Sonnet
  drives the loop alone for v1.
- **Token-by-token authoritative cost accounting.** LangSmith
  surfaces per-trace token usage; we do not duplicate it.
- **Pinecone Postgres checkpointer**, `Store` API, or any LangGraph
  v1 long-term memory primitive. `InMemorySaver` only.
- **Postgres ping inside `/health`** (`dependencies` payload stays
  `{}`). Revisit at TM-A5.
- **Frontend wiring of `/chat/stream` and `/chat/{tid}/history`** →
  TM-E3.
- **Linear MCP work to update Linear `TM-18` status.** PR body
  closes the issue; Linear handles the transition.
- **A new ADR.** No architectural irreversibility:
  - `create_react_agent` choice is a single import change away from
    Option B if profiling demands.
  - The two new deps are reversible.
  - Chat-messages table is additive and non-breaking.
- **Concurrent posts to the same `thread_id`.** Behaviour is
  undefined for v1 (research §14.12). The frontend will single-flight
  by convention.
- **`langgraph-checkpoint-postgres` dependency.** Skipped per
  decision §2.6.
- **Refactor of `src/agent/` (the TM-D1 stub).** That dir lives at
  `src/agent/` (no `api.` prefix); we keep it untouched. The new
  agent code lives at `src/api/agent/` so the FastAPI app's
  imports stay flat (`from api.agent.graph import compile_agent`)
  and the WP is single-track. The stub is left as-is.

## 5. Implementation phases (Phase 3)

Nine internal phases. Each ends with `uv run task lint && uv run task test`
clean before proceeding. If any phase diverges from the plan, **stop
and report**.

### Phase 3.1 — Deps + scaffolding

- `pyproject.toml`: add to `[project].dependencies`
  - `langchain-anthropic>=0.3`
  - `llama-index-vector-stores-pinecone>=0.4`
- `uv lock` to regenerate `uv.lock`. Verify both new packages and
  their transitive `langchain-core` 1.x continue to resolve.
- Create empty `src/api/agent/__init__.py` and the five sibling
  files as empty modules so subsequent imports do not fail.
- Sanity: `uv run python -c "from langchain_anthropic import ChatAnthropic; from llama_index.vector_stores.pinecone import PineconeVectorStore; print('ok')"`.

**Phase exit:** existing `tests/api/test_*` and `tests/test_health.py`
keep passing. `mypy strict` green on the empty stubs.

### Phase 3.2 — Pydantic AI line-id normaliser

`src/api/agent/extraction.py`:

```python
"""Pydantic AI line-id normaliser.

Maps free-text line names ("Lizzy", "Lizzie", "Elizabeth Line") to
the canonical TfL ``line_id``. Used inside ``query_line_reliability``
when the LLM-supplied ``line_id`` is not already a canonical token.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent

CanonicalLineId = Literal[
    "bakerloo", "central", "circle", "district",
    "hammersmith-city", "jubilee", "metropolitan",
    "northern", "piccadilly", "victoria",
    "waterloo-city", "elizabeth",
]


class LineId(BaseModel):
    line_id: CanonicalLineId


@lru_cache(maxsize=1)
def _normaliser() -> Agent[None, LineId]:
    return Agent(
        "anthropic:claude-3-5-haiku-latest",
        output_type=LineId,
        instructions=(
            "Map the user's mention of a London Underground or Elizabeth "
            "line to its canonical line_id. Never invent unfamiliar lines."
        ),
    )


async def normalise_line_id(text: str) -> str | None:
    """Return canonical ``line_id`` for ``text`` or ``None`` if unknown."""
    if text in _CANONICAL:
        return text
    try:
        result = await _normaliser().run(text)
    except Exception:  # noqa: BLE001 — boundary; LangSmith captures
        return None
    return result.output.line_id


_CANONICAL = {*LineId.model_fields["line_id"].annotation.__args__}  # type: ignore[union-attr]
```

Tests in `tests/agent/test_extraction.py` use Pydantic AI's
`pydantic_ai.models.test.TestModel` (or `FunctionModel`) so the
real Anthropic API is never called. Cases:

| Case | Input | Expected |
|---|---|---|
| canonical pass-through | `"piccadilly"` | `"piccadilly"`, no Haiku call |
| Lizzy slang | `"Lizzy line"` | `"elizabeth"` |
| typo | `"piccadily"` | `"piccadilly"` |
| nonsense | `"my favourite stop"` | `None` |

### Phase 3.3 — Tools and prompts

`src/api/agent/tools.py`:

```python
"""LangChain tools wrapping the TM-D2/D3 fetchers and the RAG retriever."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from langchain_core.tools import tool
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from api.agent.extraction import normalise_line_id
from api.agent.rag import build_retriever, retrieve  # see Phase 3.4
from api.db import (
    fetch_bus_punctuality, fetch_live_status,
    fetch_recent_disruptions, fetch_reliability,
    BUS_PUNCTUALITY_WINDOW_DAYS,
)
from api.schemas import Mode

# Pydantic input schemas as locked in §2 above ...

def make_tools(*, pool: AsyncConnectionPool, retriever: Any) -> list[Any]:
    """Build the five LangGraph tools bound to a specific pool + retriever."""

    @tool(args_schema=type(None))  # no-arg tool
    async def query_tube_status() -> list[dict[str, Any]]:
        """Return the current operational status of every line right now."""
        rows = await fetch_live_status(pool)
        return [r.model_dump() for r in rows]

    @tool(args_schema=LineReliabilityQuery)
    async def query_line_reliability(line_id: str, window_days: int = 7) -> dict[str, Any] | str:
        """Return reliability for a line over a window (default 7 days)."""
        canonical = await normalise_line_id(line_id)
        if canonical is None:
            return f"Unknown line: {line_id!r}"
        result = await fetch_reliability(pool, line_id=canonical, window=window_days)
        return result.model_dump() if result else f"No reliability data for {canonical}."

    # … query_recent_disruptions, query_bus_punctuality, search_tfl_docs

    return [query_tube_status, query_line_reliability, ...]
```

The `search_tfl_docs` body delegates to `retrieve(retriever, query, doc_id, top_k)`
(Phase 3.4) and projects each hit to a flat dict the LLM can read
(`doc_title`, `section_title`, `page_start`, `page_end`, `text`,
`score`, `resolved_url`).

`src/api/agent/prompts.py`:

```python
"""System prompt for the tfl-monitor chat agent."""

from datetime import date as _date

SYSTEM_PROMPT_TEMPLATE = """You are tfl-monitor's assistant for London transport.
Tools:
- query_tube_status: live status per line right now.
- query_line_reliability: reliability for a single line over a window
  (default 7 days).
- query_recent_disruptions: most recent disruptions, optionally scoped
  by mode (tube, bus, dlr, ...).
- query_bus_punctuality: per-bus-stop punctuality. Note: this is a
  proxy on prediction freshness, not a ground-truth on-time KPI;
  cite that caveat when you use it.
- search_tfl_docs: passages from TfL strategy docs (Business Plan,
  Mayor's Transport Strategy, Annual Report). Use for policy or
  forecast questions; cite by doc_title + page_start.

Pick the smallest tool set that answers. Today is {today}."""


def render(today: str | None = None) -> str:
    today = today or _date.today().isoformat()
    return SYSTEM_PROMPT_TEMPLATE.format(today=today)
```

### Phase 3.4 — RAG retriever

`src/api/agent/rag.py`:

```python
"""LlamaIndex retrieval over the Pinecone tfl-strategy-docs index."""

from __future__ import annotations

import asyncio
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.pinecone import PineconeVectorStore
from pinecone import Pinecone
from pydantic import BaseModel

NAMESPACES = ("tfl_business_plan", "mts_2018", "tfl_annual_report")


class TflDocSnippet(BaseModel):
    doc_id: str
    doc_title: str
    section_title: str
    page_start: int | None
    page_end: int | None
    text: str
    score: float
    resolved_url: str


def build_retriever(*, pinecone_api_key: str, openai_api_key: str,
                    index_name: str) -> dict[str, Any]:
    """Build per-namespace retrievers; returned dict is namespace → retriever."""
    pc = Pinecone(api_key=pinecone_api_key)
    pinecone_index = pc.Index(index_name)
    embed_model = OpenAIEmbedding(model="text-embedding-3-small",
                                  api_key=openai_api_key)
    return {
        ns: VectorStoreIndex.from_vector_store(
            PineconeVectorStore(pinecone_index=pinecone_index, namespace=ns),
            embed_model=embed_model,
        ).as_retriever(similarity_top_k=5)
        for ns in NAMESPACES
    }


async def retrieve(
    retrievers: dict[str, Any], *,
    query: str, doc_id: str | None, top_k: int,
) -> list[TflDocSnippet]:
    targets = [doc_id] if doc_id else list(NAMESPACES)
    coros = [_one(retrievers[ns], query) for ns in targets]
    nested = await asyncio.gather(*coros)
    flat = [hit for hits in nested for hit in hits]
    flat.sort(key=lambda h: h.score, reverse=True)
    return flat[:top_k]


async def _one(retriever: Any, query: str) -> list[TflDocSnippet]:
    nodes = await retriever.aretrieve(query)
    return [_to_snippet(node) for node in nodes]


def _to_snippet(node: Any) -> TflDocSnippet:
    meta = node.metadata or {}
    page_start = meta.get("page_start")
    page_end = meta.get("page_end")
    return TflDocSnippet(
        doc_id=meta.get("doc_id", ""),
        doc_title=meta.get("doc_title", ""),
        section_title=meta.get("section_title", ""),
        page_start=None if page_start in (-1, None) else int(page_start),
        page_end=None if page_end in (-1, None) else int(page_end),
        text=meta.get("text", node.text or ""),
        score=float(node.score or 0.0),
        resolved_url=meta.get("resolved_url", ""),
    )
```

The `-1 → None` map mirrors the TM-D4 sentinel encoding.

### Phase 3.5 — Graph compile

`src/api/agent/graph.py`:

```python
"""Compile the LangGraph chat agent."""

from __future__ import annotations

import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from psycopg_pool import AsyncConnectionPool

from api.agent.prompts import render
from api.agent.rag import build_retriever
from api.agent.tools import make_tools


def compile_agent(*, pool: AsyncConnectionPool) -> Any | None:
    """Build the agent or return ``None`` if any required key is missing."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    pinecone_key = os.environ.get("PINECONE_API_KEY")
    pinecone_index = os.environ.get("PINECONE_INDEX", "tfl-strategy-docs")
    if not (anthropic_key and openai_key and pinecone_key):
        return None
    model = ChatAnthropic(
        model_name="claude-3-5-sonnet-latest",
        temperature=0.0,
        anthropic_api_key=anthropic_key,
    )
    retriever = build_retriever(
        pinecone_api_key=pinecone_key,
        openai_api_key=openai_key,
        index_name=pinecone_index,
    )
    tools = make_tools(pool=pool, retriever=retriever)
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=render(),
        checkpointer=InMemorySaver(),
    )
```

### Phase 3.6 — SSE streaming + `chat_messages` schema

`contracts/sql/004_chat.sql`:

```sql
-- Chat history backing the /api/v1/chat/{thread_id}/history endpoint.
-- One row per chat turn (user or assistant). The stream handler
-- inserts the user row before yielding the first SSE frame and the
-- assistant row after the final ``end`` frame.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created
    ON analytics.chat_messages (thread_id, created_at);
```

`src/api/agent/history.py`:

```python
"""CRUD helpers for ``analytics.chat_messages``."""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api.schemas import ChatMessageResponse  # added in this WP

INSERT_SQL = """
INSERT INTO analytics.chat_messages (thread_id, role, content)
VALUES (%(thread_id)s, %(role)s, %(content)s)
"""

HISTORY_SQL = """
SELECT role, content, created_at
FROM analytics.chat_messages
WHERE thread_id = %(thread_id)s
ORDER BY created_at ASC, id ASC
"""


async def append_message(
    pool: AsyncConnectionPool, *,
    thread_id: str, role: str, content: str,
) -> None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(INSERT_SQL, {"thread_id": thread_id,
                                       "role": role, "content": content})


async def fetch_history(
    pool: AsyncConnectionPool, *, thread_id: str,
) -> list[ChatMessageResponse]:
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(HISTORY_SQL, {"thread_id": thread_id})
        rows: list[dict[str, Any]] = await cur.fetchall()
    return [ChatMessageResponse.model_validate(r) for r in rows]
```

`src/api/agent/streaming.py`:

```python
"""Project LangGraph stream events to SSE frames."""

from __future__ import annotations

import json
from typing import Any


def frame_token(text: str) -> dict[str, str] | None:
    if not text:
        return None
    return {"type": "token", "content": text}


def frame_tool(tool_name: str) -> dict[str, str]:
    return {"type": "tool", "content": tool_name}


def frame_end(content: str = "") -> dict[str, str]:
    return {"type": "end", "content": content}


def project(mode: str, payload: Any) -> list[dict[str, str]]:
    """Map a single ``(mode, payload)`` chunk to zero+ SSE frames."""
    if mode == "messages":
        chunk, _meta = payload
        text = _extract_text(getattr(chunk, "content", None))
        f = frame_token(text)
        return [f] if f else []
    if mode == "updates":
        if isinstance(payload, dict) and "tools" in payload:
            tool_messages = payload["tools"].get("messages", [])
            return [frame_tool(getattr(m, "name", "tool")) for m in tool_messages]
    return []


def _extract_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Anthropic content-block list
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def serialise(frame: dict[str, str]) -> str:
    return json.dumps(frame, ensure_ascii=False)
```

### Phase 3.7 — Lifespan + handlers in `src/api/main.py`

Add to lifespan (after pool open, before `yield`):

```python
from api.agent.graph import compile_agent

# inside lifespan ...
app.state.agent = compile_agent(pool=app.state.db_pool) if dsn else None
```

(when `DATABASE_URL` is unset, `compile_agent` is skipped; pool is
`None` and SQL tools would 503 anyway.)

Replace the 501 stubs:

```python
from sse_starlette.sse import EventSourceResponse

from api.agent.history import append_message, fetch_history
from api.agent.streaming import frame_end, project, serialise
from api.schemas import ChatMessageResponse, ChatRequest


@app.post("/api/v1/chat/stream", operation_id="post_chat_stream",
          response_model=None)
async def post_chat_stream(request: Request, body: ChatRequest) -> Response:
    pool = request.app.state.db_pool
    agent = getattr(request.app.state, "agent", None)
    if pool is None:
        return _problem(503, "Service Unavailable",
                        "Database pool is not available")
    if agent is None:
        return _problem(503, "Service Unavailable",
                        "Chat agent is not configured")

    await append_message(pool, thread_id=body.thread_id,
                         role="user", content=body.message)

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        config = {"configurable": {"thread_id": body.thread_id}}
        inputs = {"messages": [{"role": "user", "content": body.message}]}
        assistant_buffer: list[str] = []
        try:
            async for mode, payload in agent.astream(
                inputs, config=config, stream_mode=["messages", "updates"]
            ):
                if await request.is_disconnected():
                    return
                for frame in project(mode, payload):
                    if frame["type"] == "token":
                        assistant_buffer.append(frame["content"])
                    yield {"data": serialise(frame)}
            yield {"data": serialise(frame_end())}
        except asyncio.CancelledError:
            raise
        except Exception:
            logfire.exception("chat.stream.failed",
                              thread_id=body.thread_id)
            yield {"data": serialise(frame_end("error"))}
        finally:
            if assistant_buffer:
                await append_message(
                    pool, thread_id=body.thread_id,
                    role="assistant", content="".join(assistant_buffer),
                )

    return EventSourceResponse(event_stream(), ping=15)


@app.get("/api/v1/chat/{thread_id}/history",
         operation_id="get_chat_history",
         response_model=list[ChatMessageResponse])
async def get_chat_history(request: Request, thread_id: str) -> list[ChatMessageResponse] | Response:
    pool = request.app.state.db_pool
    if pool is None:
        return _problem(503, "Service Unavailable",
                        "Database pool is not available")
    rows = await fetch_history(pool, thread_id=thread_id)
    if not rows:
        return _problem(404, "Not Found",
                        f"No history for thread {thread_id}")
    return rows
```

`ChatRequest`, `ChatMessageResponse` are added to `src/api/schemas.py`
in this same phase to mirror the OpenAPI shapes.

### Phase 3.8 — Tests

#### `tests/agent/conftest.py`

- `FakeChatAnthropic` — a `langchain_core.language_models.fake_chat_models.FakeListChatModel`-like
  class that emits a deterministic AIMessage and an optional tool
  call — wired into `compile_agent` via a parameterised
  `model=...` injection point added in 3.5 (small refactor: have
  `compile_agent` accept an optional `model` override).
- `FakePineconeIndex` and `FakeRetriever` returning canned
  `NodeWithScore` lists.
- `attach_agent` fixture mirrors `attach_pool`.

#### Unit tests (default suite)

| File | Coverage |
|---|---|
| `tests/agent/test_extraction.py` | Pydantic AI `TestModel` swap; canonical pass-through; Lizzy → elizabeth; nonsense → None. |
| `tests/agent/test_sql_tools.py` | Each tool's input schema rejects out-of-range / extra fields; happy path forwards args to fakes; bus tool surfaces the proxy caveat in its docstring (asserted via `__doc__`). |
| `tests/agent/test_rag_tool.py` | `retrieve(...)` fans out to all namespaces when `doc_id is None`; queries one when specified; `-1` page sentinel mapped to `None`; results sorted by score desc. |
| `tests/agent/test_graph_compile.py` | `compile_agent(pool=…, model=FakeChatAnthropic())` returns a non-None graph; `agent.invoke(...)` with a fixed prompt yields an AIMessage; `compile_agent` returns `None` when any of the three keys is missing. |
| `tests/api/test_chat_history.py` | `GET /history` happy path (rows mapped to `ChatMessageResponse`); 404 problem when empty; 503 problem when no pool. |
| `tests/api/test_chat_stream.py` | `POST /stream` with `attach_agent(FakeAgent)` and `attach_pool(FakePool)`; assert: (1) user row written first; (2) SSE frames in expected order; (3) assistant row written at end with concatenated tokens; (4) 503 when agent missing; (5) 503 when pool missing; (6) 422 when message is empty / >4000 chars. |
| `tests/api/test_stubs.py` | Drop the two TM-D5 rows; bidirectional drift checks stay green. |

#### Integration (`-m integration`, gated)

| File | Gates | Coverage |
|---|---|---|
| `tests/integration/test_chat_history.py` | `DATABASE_URL` | `_ensure_table` creates `analytics.chat_messages` if missing; insert two rows, hit endpoint, assert ordering + 404. |
| `tests/integration/test_chat_stream.py` | `DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `PINECONE_API_KEY` | Hit live endpoint with a deterministic prompt ("Today's date?"); read SSE frames; assert ≥1 token frame and a final `end`. Marked `@pytest.mark.slow`. |
| `tests/integration/test_chat_history_after_stream.py` | same | Stream once; `GET /history`; assert two rows. |

`tests/conftest.py::FakeAsyncPool` is reused; no fork.

### Phase 3.9 — Lint, Bandit, PROGRESS, PR

- `tests/api/test_stubs.py` — drop the two TM-D5 rows.
- `PROGRESS.md` — flip TM-D5 row to ✅ with completion date and a
  paragraph note matching the verbosity of the D2/D3/D4 rows
  (≈10 lines).
- `uv run task lint`; `uv run task test`;
  `uv run bandit -r src --severity-level high`; `make check`.
- Branch: `feature/TM-D5-langgraph-agent` (mirrors D2/D3/D4 naming).
- PR title: `feat(api): TM-D5 LangGraph agent (SQL + RAG)`.
  PR body bullets:
  - LangGraph `create_react_agent` over Sonnet with five tools (4
    SQL + 1 RAG); InMemorySaver checkpointer; per-thread state.
  - SSE via sse-starlette `EventSourceResponse` with frames
    `{type: token|tool|end, content}`.
  - Pydantic AI Haiku line-id normaliser inside the reliability
    tool — earns its place per CLAUDE.md §"When to use Pydantic AI".
  - LlamaIndex `PineconeVectorStore` per-namespace fan-out over
    the TM-D4 index `tfl-strategy-docs`.
  - `analytics.chat_messages` table for `/history`. Cross-track
    touch on `contracts/sql/004_chat.sql` declared.
  - Two new deps: `langchain-anthropic`,
    `llama-index-vector-stores-pinecone`. No new env var.
  - Closes Linear `TM-18`.

## 6. Risks revisited

Carried from research §14 with mitigations locked.

| Risk | Mitigation |
|---|---|
| Missing chat-related deps in lock | Phase 3.1 adds exactly two: `langchain-anthropic`, `llama-index-vector-stores-pinecone`. `uv lock` regenerates. |
| Pool contention between agent and dashboard | Tools use `async with pool.connection() as conn` (release per query). Pool sizing stays `min=1, max=4`; revisit at TM-A5 if Supabase profiling shows saturation. |
| SSE on Vercel proxies | `ping=15` is fine on Railway; production Vercel may need `ping=9`. Note in PR body; tune at TM-E4. |
| `astream_events` deprecation | Use `astream(stream_mode=[...])` (the v1 API). Locked. |
| `MessagesState` id stability | `add_messages` reducer dedups by id; we never set client-side ids. Locked. |
| Pydantic AI version churn | `pyproject.toml` constraint `pydantic-ai>=0.0.14` already broad. `uv lock` chooses 1.85.0. |
| `/history` empty thread semantics | 404 problem when no rows match; documented in §3 acceptance criteria. |
| Cross-track `contracts/sql/` edit | Documented exception per ADR 002 §"Consequences"; PR body declares it; no new ADR. |
| Token streaming fidelity | `_frame_from` filters Anthropic content-block lists to `text` blocks only; empty token frames dropped. |
| `stream_mode="messages"` non-agent chunks | `metadata.langgraph_node` filter is currently best-effort: we accept all `messages` chunks because `create_react_agent` only emits from the agent node. If a future split graph emits sub-node chunks, the filter tightens. Note in PR body. |
| Empty `content` in tool-call AIMessageChunks | `_frame_from` returns no token frame when content is empty. Locked. |
| Concurrent thread updates | Behaviour undefined for v1; documented in §4 ("What we are NOT doing"). |
| Bandit on agent code | Strings, parameterised SQL, `SecretStr` for keys, no `shell=True`. Same gate as D2/D3 — green. |
| `mypy strict` on `langgraph` / `langchain-anthropic` / `llama-index-vector-stores-pinecone` | Add a `[[tool.mypy.overrides]]` block in `pyproject.toml` if any module ships incomplete stubs. Phase 3.1 verifies. |

### Rollback

The merge commit on `main` (call it `MERGE_SHA`) is the rollback
target. To revert:

```bash
git revert -m 1 MERGE_SHA
```

Reverts the WP cleanly:

- Two new deps stay in `uv.lock` until `uv lock --regenerate`; no
  runtime impact (handlers fall back to the 501 stubs the revert
  restores).
- `analytics.chat_messages` table remains in any DBs that already
  applied `004_chat.sql`; it is additive and harmless. To physically
  remove: `DROP TABLE IF EXISTS analytics.chat_messages;` (manual).
- `app.state.agent` slot vanishes (the `getattr(..., None)` fallback
  in any temporary read-side keeps things safe).

## 7. Diff size estimate

Estimate (Phase 3 budget, source + tests):

| File | Source LoC | Test LoC |
|---|---|---|
| `src/api/agent/__init__.py` | 8 | — |
| `src/api/agent/graph.py` | 50 | — |
| `src/api/agent/tools.py` | 130 | — |
| `src/api/agent/extraction.py` | 50 | — |
| `src/api/agent/prompts.py` | 35 | — |
| `src/api/agent/streaming.py` | 70 | — |
| `src/api/agent/history.py` | 45 | — |
| `src/api/agent/rag.py` | 80 | — |
| `src/api/main.py` (delta) | 60 | — |
| `src/api/schemas.py` (delta: `ChatRequest`, `ChatMessageResponse`) | 25 | — |
| `contracts/sql/004_chat.sql` | 25 | — |
| `tests/agent/conftest.py` | — | 80 |
| `tests/agent/test_extraction.py` | — | 70 |
| `tests/agent/test_sql_tools.py` | — | 110 |
| `tests/agent/test_rag_tool.py` | — | 80 |
| `tests/agent/test_graph_compile.py` | — | 60 |
| `tests/api/test_chat_history.py` | — | 80 |
| `tests/api/test_chat_stream.py` | — | 130 |
| `tests/integration/test_chat_history.py` | — | 70 |
| `tests/integration/test_chat_stream.py` | — | 60 |
| `tests/integration/test_chat_history_after_stream.py` | — | 50 |
| **Totals** | **~580** | **~790** |

Combined ~1370 LoC. Crosses the implicit 600-LoC threshold (TM-D3
plan §1).

### Split strategy (if required)

Phase 3 may opt to split into a sequence of two PRs **only if** the
single-PR review proves unwieldy:

- **TM-D5a** (~700 LoC): graph + tools + prompts + extraction +
  streaming projection + the lifespan compile + the `/chat/stream`
  handler + unit tests for tools/extraction/graph. Stubs `/history`
  to 501 with hint `TM-D5b`.
- **TM-D5b** (~670 LoC): `chat_messages` table, history fetcher,
  history endpoint, `/chat/stream` persistence side-effect, history
  unit/integration tests, `STUB_ROUTES` cleanup, `PROGRESS.md`.

Default: **single PR**. The split is a fallback if reviewers ask for
it. Either path keeps every WP completion criterion intact.

## 8. Files expected to change (summary)

New (19):

- `src/api/agent/{__init__,graph,tools,extraction,prompts,streaming,history,rag}.py`
- `contracts/sql/004_chat.sql`
- `tests/agent/{__init__,conftest,test_extraction,test_sql_tools,test_rag_tool,test_graph_compile}.py`
- `tests/api/test_chat_history.py`
- `tests/api/test_chat_stream.py`
- `tests/integration/test_chat_history.py`
- `tests/integration/test_chat_stream.py`
- `tests/integration/test_chat_history_after_stream.py`

Modified (5):

- `pyproject.toml` (+2 deps)
- `uv.lock` (regenerated)
- `src/api/main.py` (lifespan + two handlers, drop the two
  `_not_implemented` bodies)
- `src/api/schemas.py` (add `ChatRequest`, `ChatMessageResponse`)
- `tests/api/test_stubs.py` (drop two TM-D5 rows)
- `PROGRESS.md` (TM-D5 → ✅)

Untouched:

- `contracts/openapi.yaml`, `contracts/schemas/*`, `dbt/`,
  `web/`, `src/ingestion/`, `src/rag/`, `src/agent/` (TM-D1 stub),
  `airflow/`, `Makefile`, `docker-compose.yml`, `.env.example`.

## 9. Confirmation gate

Before starting Phase 3:

1. Read `.claude/specs/TM-D5-research.md` and this plan side-by-side.
2. Confirm `uv lock` resolves `langchain-anthropic` and
   `llama-index-vector-stores-pinecone` cleanly on the local
   platform without dependency resolver conflicts.
3. Confirm the LangGraph v1 import paths resolve:
   `from langgraph.prebuilt import create_react_agent`,
   `from langgraph.checkpoint.memory import InMemorySaver`,
   `from langchain_anthropic import ChatAnthropic`.
4. Confirm `from llama_index.vector_stores.pinecone import PineconeVectorStore`
   imports without pulling in the legacy `pinecone-client` lib (the
   adapter must use the `pinecone` 5.x SDK already in lock).
5. Verify the `analytics` schema is populated by dbt
   (`dbt/profiles.yml::schema: analytics`); the new `chat_messages`
   table lives there but is API-owned (not a dbt source).

If any of the above surfaces a surprise, **stop and report**:

> *Expected: X. Found: Y. How should I proceed?*
