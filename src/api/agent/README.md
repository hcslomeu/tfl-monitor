# src/api/agent/

The LangGraph chat agent: `create_react_agent` over four live TfL tools,
Anthropic Claude as the model, and an SSE projection for streaming.

## Layout

```text
src/api/agent/
├─ __init__.py
├─ graph.py          # compile_agent(): None when ANTHROPIC_API_KEY is unset
├─ tools.py          # query_tube_status, query_recent_disruptions,
│                    # plan_journey_tool, get_arrivals_tool
├─ prompts.py        # System prompt + tool instructions
└─ streaming.py      # LangGraph stream → SSE frame projector
```

## Model

`ChatAnthropic` against the Anthropic API direct (ADR 015). The model id
comes from `CHAT_MODEL` (default `claude-haiku-5-5`) with `effort: low`, a
4096-token response cap, and automatic prompt caching. Spend is capped by
the Anthropic Console workspace that issued the key; when Anthropic rejects
a call, `/chat/stream` emits a readable `token` frame followed by
`end: "error"`. A LangGraph `recursion_limit` of 12 bounds tool loops.

## Frames

`{type, content}` is the stable contract with the frontend:

| `type` | `content` |
|--------|-----------|
| `token` | streamed assistant text |
| `tool` | name of the tool just called |
| `journey` / `arrivals` | JSON-encoded card view (ADR 011) |
| `end` | `""` on success, `"error"` on failure |

## Memory

Conversation memory is the in-process `InMemorySaver`, keyed by
`thread_id`. Nothing is persisted; a cold start or another function
instance starts the thread fresh.

## Tests

Unit tests use a fake chat model and fake TfL clients, so they never spend
LLM budget. `tests/integration/test_chat_stream.py` hits the live stack and
is gated on `ANTHROPIC_API_KEY` + `TFL_APP_KEY` (`-m "integration and slow"`).
