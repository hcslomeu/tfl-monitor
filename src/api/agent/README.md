# src/api/agent/

The LangGraph agent — `create_react_agent` over five typed tools, a Pydantic
AI Haiku normaliser for `LineId`, an SSE projection for streaming, and a
history adapter that persists chat turns into `analytics.chat_messages`.

## Layout

```text
src/api/agent/
├─ __init__.py
├─ graph.py          # compile_agent() — returns None if any 3 keys missing
├─ tools.py          # 4 SQL tools (wraps src/api/db.py fetchers)
├─ rag.py            # 1 RAG tool — LlamaIndex retriever over Pinecone
├─ extraction.py     # Pydantic AI Haiku → LineId
├─ prompts.py        # System prompt + tool instructions
├─ streaming.py      # LangGraph stream → SSE Frame projector
└─ history.py        # analytics.chat_messages reader/writer
```

## Compilation

```python
def compile_agent() -> CompiledGraph | None:
    if not (anthropic_key and openai_key and pinecone_key):
        return None
    model = _build_chat_model()           # Sonnet, temperature=0
    tools = [
        query_tube_status,                # → /status/live fetcher
        query_line_reliability,           # → /reliability fetcher (with LineId normaliser)
        query_recent_disruptions,         # → /disruptions/recent fetcher
        query_bus_punctuality,            # → bus/.../punctuality fetcher
        search_tfl_docs,                  # → Pinecone retriever (3 namespaces)
    ]
    return create_react_agent(model, tools, checkpointer=InMemorySaver())
```

`compile_agent` returns `None` when any of `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `PINECONE_API_KEY` is missing, so the FastAPI lifespan
caches `None` on `app.state.agent` and `/chat/stream` 503s gracefully while
the rest of the app keeps serving.

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
| `rag.py` | 6 | Retrieval, doc_id targeting, page sentinel, namespace fan-out, empty, sdk failure |
| `graph.py` | 5 | Compile, no-keys, tool registration, model selection, prompt |
| Route smokes | 9 | SSE happy / 503 / mid-stream `end:error`; history happy / empty / 503 |

All run with fakes for Anthropic / OpenAI / Pinecone — no live LLM cost in
unit tests. Integration smokes are gated on the four-key combo plus
`DATABASE_URL`.

## Bedrock swap (TM-A5)

Once TM-A5 ships, this package will switch from `ChatAnthropic` /
`anthropic:...` to `ChatBedrockConverse` / `bedrock:...` driven by the
`BEDROCK_REGION` env var. Anthropic-direct stays as a local-dev fallback —
see [Deployment](../../../docs/deployment.md) for the full design.
