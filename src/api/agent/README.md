# src/api/agent/

The LangGraph agent — `create_react_agent` over four SQL tools (plus the
pgvector RAG tool when reachable), a Pydantic AI Haiku normaliser for
`LineId`, an SSE projection for streaming, and a history adapter that
persists chat turns into `analytics.chat_messages`.

## Layout

```text
src/api/agent/
├─ __init__.py
├─ graph.py          # compile_agent() — None when no LLM backend; RAG optional
├─ tools.py          # 4 SQL tools (+ search_tfl_docs when a retriever is given)
├─ rag.py            # RAG tool — LlamaIndex retriever over pgvector
├─ extraction.py     # Pydantic AI Haiku → LineId
├─ prompts.py        # System prompt + tool instructions
├─ streaming.py      # LangGraph stream → SSE Frame projector
└─ history.py        # analytics.chat_messages reader/writer
```

## Compilation

```python
def compile_agent(*, pool) -> CompiledGraph | None:
    chat_model = _build_chat_model()      # Bedrock Sonnet, else Anthropic; None if neither
    if chat_model is None:
        return None
    retriever = _build_retriever_or_none()  # pgvector index, or None when no DSN
    tools = make_tools(pool=pool, retriever=retriever)
    return create_react_agent(chat_model, tools, prompt=render(), checkpointer=InMemorySaver())
```

`compile_agent` returns `None` only when no LLM backend is configured
(neither `BEDROCK_REGION` nor `ANTHROPIC_API_KEY`), so the FastAPI lifespan
caches `None` on `app.state.agent` and `/chat/stream` 503s gracefully. The
RAG tool is **optional**: with no Postgres DSN the agent still serves the
four SQL tools; an unreachable pgvector store degrades to zero snippets
rather than failing the request.

## Streaming

```python
async def project(stream: AsyncIterator[tuple[str, Any]]) -> AsyncIterator[Frame]:
    async for kind, payload in stream:
        if kind == "messages":
            yield Frame(type="token", content=payload.content)
        elif kind == "updates":
            for tool_name in _tool_calls_from(payload):
                yield Frame(type="tool", content=tool_name)
    yield Frame(type="end", content="ok")
```

`Frame` is the **stable contract** with the frontend:
`{type: "token" | "tool" | "end", content: str}`. Replacing LangGraph would
not change a single line in the web client.

## Persistence

Chat turns land in `analytics.chat_messages` (DDL in
`contracts/sql/004_chat.sql`):

| Step | When |
|------|------|
| Insert user turn | Before the first frame is sent — a connection drop never loses the question |
| Insert assistant turn | On stream end with the concatenated tokens |

The `/chat/{thread_id}/history` endpoint replays the table ordered by
`(thread_id, created_at ASC)`.

## Tests

| Module | Count | What it covers |
|--------|-------|----------------|
| `extraction.py` | 4 | Canonical / informal / ambiguous / empty `LineId` |
| `tools.py` | 8 | Happy path, empty, parameter validation, db absent |
| `rag.py` | 5 | No-filter, doc_id metadata filter, page sentinel, score sort, store-failure |
| `graph.py` | 7 | No-backend, smoke invoke, retriever-on/off, model selection |
| Route smokes | 9 | SSE happy / 503 / mid-stream `end:error`; history happy / empty / 503 |

All run with fakes for Anthropic / Bedrock / pgvector — no live LLM cost in
unit tests. Integration smokes are gated on a live LLM backend plus
`DATABASE_URL`.

## LLM backend

Bedrock is the production backend: set `BEDROCK_REGION` +
`BEDROCK_SONNET_MODEL_ID` and `ChatBedrockConverse` is selected, with boto3
reading the standard credential chain. Leave `BEDROCK_REGION` unset and
provide `ANTHROPIC_API_KEY` for the local-dev `ChatAnthropic` fallback. RAG
embeddings use Bedrock Titan v2 over the same credentials, and the vectors
live in pgvector.
