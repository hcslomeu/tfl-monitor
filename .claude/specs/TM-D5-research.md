# TM-D5 — Research (Phase 1)

Read-only investigation for **TM-D5: LangGraph agent (SQL + RAG +
Pydantic AI)** — Linear `TM-18`, track `D-api-agent`, phase 6 in
`PROGRESS.md`. Output of this phase is a list of facts, options, and
open questions. Design decisions are committed in
`.claude/specs/TM-D5-plan.md` (Phase 2). Structure mirrors
`TM-D3-research.md`.

## 1. Charter, scope, and ADR conflicts

### What TM-D5 owns

`PROGRESS.md` row + Linear `TM-18`:

> TM-D5 — *LangGraph agent (SQL + RAG + Pydantic AI)* — track
> `D-api-agent`, phase 6, depends on TM-D2 (live SQL endpoints in
> `main`), TM-D3 (disruptions + bus endpoints in `main`), and TM-D4
> (Pinecone index `tfl-strategy-docs` populated).

The two TM-D5-keyed routes that still 501 in
`tests/api/test_stubs.py::STUB_ROUTES`:

| Method | Path | OpenAPI operationId | Handler today |
|---|---|---|---|
| POST | `/api/v1/chat/stream` | `post_chat_stream` | `_not_implemented("Not implemented — see TM-D5")` |
| GET | `/api/v1/chat/{thread_id}/history` | `get_chat_history` | same |

Out of scope (still 501 after TM-D5): nothing — these are the last 501
stubs. Bidirectional drift checks remain.

### Hard dependencies (already in `main`)

- **TM-D2**: `src/api/db.py` exposes
  `fetch_live_status`, `fetch_status_history`, `fetch_reliability`,
  the SQL constants `LIVE_STATUS_SQL`, `HISTORY_SQL`,
  `RELIABILITY_AGG_SQL`, `RELIABILITY_HISTOGRAM_SQL`, and the
  `AsyncConnectionPool` factory `build_pool(dsn)`.
- **TM-D3**: same module exposes `fetch_recent_disruptions`,
  `fetch_bus_punctuality`, `BUS_PUNCTUALITY_WINDOW_DAYS = 7`,
  `BUS_PUNCTUALITY_SQL`, `BUS_STOP_NAME_SQL`, `DISRUPTIONS_SQL`. The
  bus query is a *documented proxy* on `time_to_station_seconds`; the
  RAG/SQL agent must cite that caveat when surfacing the number.
- **TM-D4**: `src/rag/` package and Pinecone index
  `tfl-strategy-docs` (1536 dim, cosine, AWS `us-east-1`), one
  namespace per `doc_id` (`tfl_business_plan`, `mts_2018`,
  `tfl_annual_report`). Vector id = `sha256("{resolved_url}::{chunk_index}")`.
  Metadata keys upserted into Pinecone:
  `doc_id, doc_title, resolved_url, chunk_index, section_title,
  page_start, page_end, text` (per
  `src/rag/upsert.py::upsert_chunks`).

### Track scope (CLAUDE.md §"WP scope rules")

Track is `D-api-agent`. Allowed directories: `src/api/`, `src/agent/`,
`src/rag/` (read-only here — D4 owns it), `tests/api/`,
`tests/integration/`, `tests/agent/` (new). **Touching `dbt/`,
`web/`, `src/ingestion/`, `airflow/`, `contracts/`, `Makefile`, or
`docker-compose.yml` is out of scope** and would warrant a stop-and-ask.

### ADR scan — no conflicts

| ADR | Relevance to TM-D5 | Conflict? |
|---|---|---|
| 001 — Redpanda over Kafka | Streaming broker; agent does not touch Kafka. | No. |
| 002 — Contracts-first parallelism | `contracts/openapi.yaml` chat endpoints frozen. SSE frame shape is hand-written description (see §2). | No — TM-D5 implements; does not edit. |
| 003 — Airflow on Railway | Production deploy concern; orthogonal. | No. |
| 004 — Logfire + LangSmith split | Direct mandate for this WP — split is exactly what TM-D5 needs (LangSmith for nodes/tools/LLM, Logfire for FastAPI/psycopg/httpx). | No — adopted as-is. |
| 005 — DB-side defaults on `raw.*` | Ingestion concern. | No. |

No new ADR is required to ship TM-D5. The lean rules (CLAUDE.md
Principle #1) constrain abstractions — see §3 for graph topology
choices.

### Repo-state surprises discovered during research

1. **Missing chat-related deps in `pyproject.toml` / `uv.lock`.** The
   brief assumes `langchain-anthropic`, a checkpointer backend
   (`langgraph-checkpoint-postgres` or `langgraph-checkpoint-sqlite`),
   and `llama-index-vector-stores-pinecone` are already declared.
   Confirmed absent (`grep` on both files):
   - `langchain-anthropic` — required for `ChatAnthropic` /
     `init_chat_model("anthropic:claude-...")` so LangGraph can bind
     Pydantic-typed tools to a Claude model.
   - `langgraph-checkpoint-postgres` (or `-sqlite`) — required for
     persistent thread checkpoints; `langgraph-checkpoint` itself is
     in the lock as a transitive (`4.0.2`), but only the in-memory
     `InMemorySaver` ships with it.
   - `llama-index-vector-stores-pinecone` — required for the
     `PineconeVectorStore` adapter; only `llama-index-core` and
     `llama-index-embeddings-openai` are in the lock today.
   - `llama-index-llms-anthropic` — only needed if we route the synth
     LLM call through LlamaIndex; if LangGraph drives the model
     directly via `ChatAnthropic`, this is not required (lean: skip).
   These additions land in Phase 3.1 of the plan; explicit decision
   required in plan §2.
2. **`src/agent/` is a TM-D1 stub.** `src/agent/graph.py` defines a
   no-op `StateGraph` with one `noop` node and a TypedDict
   `AgentState`; `validate_langsmith_env()` runs at import time. This
   stub is a starting point only — TM-D5 replaces the body wholesale.
3. **No chat history / messages table in `contracts/sql/`.** Two
   pre-existing init scripts (`001_raw_tables.sql`,
   `002_reference_tables.sql`, `003_indexes.sql`) — none addresses
   chat persistence. See §9 for trade-offs.
4. **`logfire.instrument_psycopg("psycopg")` already wired** in
   `src/api/observability.py`. Any agent code that runs SQL through
   the same pool inherits the trace.

## 2. External API surface

### `POST /api/v1/chat/stream`

OpenAPI body (`contracts/openapi.yaml`):

```yaml
ChatRequest:
  required: [thread_id, message]
  thread_id: string
  message:   string, minLength=1, maxLength=4000
```

Response: `200 text/event-stream`; spec literally says

> *Each `data:` frame contains a JSON payload with at least
> `{"type": "token" | "tool" | "end", "content": <str>}`.*

The "at least" leaves room for additional fields (e.g. `tool_name`,
`thread_id`, an `error` type for caller-visible failures), but the
core three event types are normative. Clients (TM-E3) will key off
`type` for routing, so we must not invent new types without a
contract update.

`400` → invalid `ChatRequest` (covered by FastAPI body validation,
RFC 7807 envelope wrapping is *not* required for FastAPI's default
422 — we keep that as-is, mirroring TM-D2 §3 plan §3 behaviour for
422). `500` → RFC 7807.

### `GET /api/v1/chat/{thread_id}/history`

Response: `200 application/json` with `ChatMessage[]`:

```yaml
ChatMessage:
  required: [role, content, created_at]
  role:       enum [user, assistant, system]
  content:    string
  created_at: string, format=date-time
```

`404` when the thread does not exist; `500` on infra error.

### Drift considerations

- `tests/api/test_stubs.py` will fail when the two routes stop
  returning 501. Mitigation: drop the rows from `STUB_ROUTES` in the
  same PR (mirrors TM-D2/D3 plan §3).
- The bidirectional OpenAPI drift checks
  (`test_every_app_route_declares_operation_id`,
  `test_spec_operation_ids_have_matching_routes`,
  `test_app_routes_have_matching_spec_entries`) require the new
  handlers to keep `operation_id="post_chat_stream"` /
  `"get_chat_history"`.
- The SSE response is `text/event-stream`, not JSON. FastAPI's
  auto-OpenAPI generator only declares response shapes for routes
  with `response_model`; the OpenAPI YAML hand-codes the
  `text/event-stream` content type already, so we set
  `response_model=None` on `post_chat_stream` (matches the existing
  501 stub) and rely on the YAML for shape documentation. The drift
  checks compare `operationId` only, so this remains green.

## 3. Agent topology survey (LangGraph v1.x)

Resolved versions (`uv.lock`): `langgraph 1.1.9`,
`langgraph-checkpoint 4.0.2`, `langgraph-prebuilt 1.0.10`,
`langchain-core 1.3.0`, `anthropic 0.96.0`. Context7 query at
`/langchain-ai/langgraph` confirmed `create_react_agent` and
`InMemorySaver` are the v1 surface (queries: "v1.x StateGraph
create_react_agent astream_events tool node Anthropic checkpointer";
"stream_mode messages token-level streaming for SSE; astream_events
v2; emit chunks on tool start and tool end").

### Topology options

#### Option A — `create_react_agent` prebuilt

```python
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

agent = create_react_agent(
    model=ChatAnthropic(model="claude-3-5-sonnet-...", temperature=0),
    tools=[query_tube_status, query_line_reliability,
           query_recent_disruptions, query_bus_punctuality,
           search_tfl_docs],
    prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)
```

- **Pros**: ~10 lines of glue; LangGraph maintains the
  agent-tool-loop wiring, including the model's tool-call → tool-node
  → back-to-model edge. LangSmith auto-instruments every call. Stream
  modes (`updates`, `messages`, `values`) work out of the box.
- **Cons**: single-model loop, no separate "router" vs "synth" model.
  If we want Haiku→Sonnet (CLAUDE.md tech-stack), we either accept
  Sonnet-only or hand-roll a graph (Option B).
- Routing model choice: `create_react_agent` runs one model. With
  Sonnet only, the cost-vs-latency table in CLAUDE.md is partially
  ignored (Haiku for routing). Acceptable because the tool-calling
  decisions are tiny prompts on Sonnet — overhead modest, ~$0.003 per
  conversation.

#### Option B — hand-rolled `StateGraph`

```python
graph = StateGraph(MessagesState)
graph.add_node("router", router_node)         # Haiku
graph.add_node("tools", ToolNode(tools))      # built-in
graph.add_node("synth", synth_node)           # Sonnet
graph.add_conditional_edges("router", route_decider,
                            {"tools": "tools", "synth": "synth"})
graph.add_edge("tools", "synth")
graph.set_entry_point("router")
```

- **Pros**: explicit Haiku→Sonnet split. Easier to observe in
  LangSmith ("router decided X with Haiku, synth answered with
  Sonnet"). Easier to test individual nodes.
- **Cons**: ~80 LoC of graph wiring; manual tool-call extraction (the
  router emits tool calls via `bind_tools` then we `ToolNode` them);
  more places to drift from the prebuilt's correctness. Lean rules
  (Principle #1) push back: 200 lines of "well-structured" loses to
  40 lines that do the same thing.

#### Option C — `create_react_agent(..., pre_model_hook=...)` for routing

LangGraph 1.x `create_react_agent` supports `pre_model_hook` /
`post_model_hook` and `response_format` for structured output. A
Haiku pre-hook could decide "this is small-talk, skip tools" before
the Sonnet call. **Rejected as YAGNI**: the chat surface is
"answer factual questions about TfL"; the model already decides
not to call tools when not needed.

### Recommendation for plan §2

**Option A** (`create_react_agent`) on **Sonnet only** for v1, with
the system prompt instructing the model to call SQL tools first when
the question is operational/quantitative and `search_tfl_docs` when
the question is strategic/policy. Defer Haiku routing to a follow-up
WP if cost is observed to creep. Records the trade-off in plan §4
("What we are NOT doing").

### State schema

LangGraph v1 ships `langgraph.graph.MessagesState` (subclass of
`TypedDict` with a `messages: Annotated[list[AnyMessage],
add_messages]`). Our chat surface is exactly that. **No custom
state needed.** Adding fields like `last_tool` or `intent` would be
abstract-without-a-second-consumer (Principle #1 rule 4).

### Streaming surface

LangGraph v1 stream modes (per context7):

- `stream_mode="updates"` — one event per node finishing, payload =
  the partial state diff. Coarse-grained.
- `stream_mode="values"` — full state after each step. Heaviest.
- `stream_mode="messages"` — token-level deltas from the LLM, each
  event is `(message_chunk, metadata)`. **This is the one we want
  for SSE token streaming.**
- `stream_mode="custom"` — `StreamWriter` injection inside nodes.
  Not needed.
- `astream_events` (v2) — the legacy fine-grained event API; adds
  ~3× overhead vs `astream` and is being deprecated. **Avoid.**

We can request multiple modes simultaneously:
`stream_mode=["messages", "updates"]`. Each yielded chunk is then a
tuple `(mode, data)` (LangGraph v1 spec). This lets us emit:

- `messages` → SSE `{"type":"token","content":<delta>}`
- `updates` (filtered to `ToolNode`/`tools` keys) → SSE
  `{"type":"tool","content":<tool_name>}`
- a final `{"type":"end","content":""}` when `astream` exhausts.

## 4. SQL tool design

Two routes from the LLM tool to the warehouse.

### Option A — tools call FastAPI endpoints (HTTP self-call)

Tool body does `httpx.AsyncClient().get(f"http://{HOST}:{PORT}/api/v1/status/live")`.

- **Pros**: one source of truth (the same shapes the dashboard
  consumes); reuses the OpenAPI contract; trivial to test against
  `TestClient`.
- **Cons**: an extra hop per tool call (~5 ms localhost, more in
  prod); the agent's process needs to know its own URL; SQL
  parameterisation is double-marshalled (params → query string →
  back to dict in the handler). On Railway, the agent runs in the
  same container as FastAPI, so HTTP self-call is inverse to the
  monorepo pattern (everything else uses the pool directly).

### Option B — tools call the existing async fetchers directly

`src/api/db.py` already exports
`fetch_live_status, fetch_status_history, fetch_reliability,
fetch_recent_disruptions, fetch_bus_punctuality`. The tools import
those functions and pass `app.state.db_pool` (the same pool the
HTTP routes use).

- **Pros**: zero serialisation overhead; one-line tool body
  (`return await fetch_live_status(pool)`); the existing TM-D2/D3
  unit tests already cover the SQL paths; the Logfire psycopg
  instrumentation already lights up.
- **Cons**: tools and HTTP routes share the connection pool. If the
  agent ties up all four connections waiting on Sonnet, the
  dashboard's `/status/live` blocks until the agent finishes. Pool
  is `min=1, max=4` — fine for a portfolio with the dashboard idle
  in dev, worth flagging in plan §9 (risks).

### Free-form SQL is not allowed (security)

Per CLAUDE.md §"Security-first" (parameterised queries, no
interpolation), the LLM must never see raw SQL or compose its own
WHERE clause. Every tool exposes a typed Pydantic input that the
fetcher binds with `%(name)s` placeholders. If a future feature
demands open-ended querying (e.g. "show me lines where reliability
dropped > 5% week-over-week"), we add a *new tool* with a typed
input — never an "exec_sql" tool.

### Tool catalogue (proposal)

| LangGraph tool | Input schema | Backed by | Notes |
|---|---|---|---|
| `query_tube_status` | `{}` (no inputs) | `fetch_live_status(pool)` | Live snapshot per line. |
| `query_line_reliability` | `LineReliabilityQuery(line_id: str, window_days: int = 7)` | `fetch_reliability(pool, line_id=..., window=...)` | `window_days` validated 1–90. |
| `query_recent_disruptions` | `RecentDisruptionsQuery(limit: int = 10, mode: Mode \| None = None)` | `fetch_recent_disruptions(pool, limit=..., mode=...)` | `limit` validated 1–200; LLM-defaulted to 10 to keep token cost low. |
| `query_bus_punctuality` | `BusPunctualityQuery(stop_id: str)` | `fetch_bus_punctuality(pool, stop_id=..., window=BUS_PUNCTUALITY_WINDOW_DAYS)` | The proxy disclaimer (§1) lives in the tool docstring so the LLM cites it. |
| `search_tfl_docs` | `TflDocSearchQuery(query: str, doc_id: Literal[...] \| None = None, top_k: int = 5)` | LlamaIndex retriever (see §5) | `doc_id` filter when set. |

Tool docstrings (the system surface the LLM actually reads) describe
*when to call*, not *how* — KISS. `query_bus_punctuality`'s docstring
must include "this is a proxy on prediction freshness, not a
ground-truth on-time KPI" so the LLM cites it in the answer.

### Recommendation for plan §2

**Option B**, direct fetcher calls, sharing `app.state.db_pool`. The
HTTP self-call hop buys nothing here.

## 5. RAG tool design

LlamaIndex 0.14.21 is already in the lock; `llama-index-core` and
`llama-index-embeddings-openai` come along. **`llama-index-vector-stores-pinecone`
is missing** (see §1). Install in plan §3.1.

### Pinecone access pattern

Per context7 (`/run-llama/llama_index`, query "PineconeVectorStore
VectorStoreIndex.from_vector_store"), the canonical wiring is:

```python
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.pinecone import PineconeVectorStore
from llama_index.embeddings.openai import OpenAIEmbedding
from pinecone import Pinecone

pc = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
pinecone_index = pc.Index("tfl-strategy-docs")

embed_model = OpenAIEmbedding(model="text-embedding-3-small")
```

### Per-namespace fan-out

TM-D4 split each `doc_id` into its own namespace. Two retrieval shapes:

#### Option A — per-doc namespace, fan out and union top-k

For each `doc_id` build a `PineconeVectorStore(pinecone_index=..., namespace=doc_id)`,
wrap in `VectorStoreIndex.from_vector_store(...)`, build a retriever,
issue `k = ceil(top_k / 3)` queries in parallel via `asyncio.gather`,
union results, sort by score, slice to `top_k`.

- **Pros**: respects the per-doc namespace structure; no doc bias
  unless the LLM explicitly requests one (`doc_id` argument, see §6
  Pydantic AI extraction).
- **Cons**: 3 round-trips per query. Each is sub-100 ms on
  Pinecone serverless, so wall time stays acceptable for chat.

#### Option B — single namespace at upsert time

Move all chunks into one namespace at ingest. Rejected — touches
TM-D4 contract.

#### Option C — accept `doc_id` argument; default behaviour = pick one

If the user asks "what does the Mayor's Transport Strategy say about
cycle lanes?", LLM picks `doc_id="mts_2018"`; for free-form
questions, LLM does not set `doc_id` and we fan out (Option A).

### Recommendation for plan §2

**Option A** with **Option C** behaviour layered on top: the tool
takes `doc_id: Literal[...] | None = None`; when provided, query a
single namespace; when None, fan out. This matches the LLM's mental
model: it can either target a doc by name (for cited questions) or
trust retrieval to pick the right one.

### Top-k and score filtering

- `top_k=5` per namespace (or per fan-out leg). Raw, no rerank.
- No score threshold — LlamaIndex's `Pinecone` retriever returns
  cosine similarity scores; we surface them in the tool output for
  the LLM to weight, but we do not filter. (Reranking via
  `LLMRerank` is YAGNI for v1.)

### What the tool returns

The chat-side LLM (Sonnet) needs enough context to compose a cited
answer. Each retrieved chunk → a small dict the model can read:

```python
@dataclass
class TflDocSnippet:
    doc_id: str
    doc_title: str
    section_title: str
    page_start: int | None       # -1 sentinel from Pinecone, mapped to None
    page_end: int | None
    text: str
    score: float
    resolved_url: str
```

Tool returns `list[TflDocSnippet]` (LangChain tools accept structured
output via Pydantic). The LLM is instructed in the system prompt to
cite `doc_title` + `page_start` (e.g. *"Source: TfL Annual Report
p.42"*).

### The `-1` page sentinel

`src/rag/upsert.py::PAGE_UNKNOWN_SENTINEL = -1` — Pinecone metadata
cannot hold `None`, so missing pages were stored as `-1`. The RAG
tool maps `-1 → None` before handing off to the LLM, so the
docstring example reads naturally.

## 6. Pydantic AI integration

CLAUDE.md §"When to use Pydantic AI" allows it for *"a tool that
needs to extract a typed struct from free text"* and forbids it as
the main agent. Concrete fit:

### Use case 1 — extracting `LineQuery` from natural language

User says *"how's the Piccadilly line been lately?"*. The LLM (via
LangGraph's `bind_tools`) already extracts `line_id="piccadilly"`,
`window_days=7` (Pydantic input on `query_line_reliability`). **No
Pydantic AI needed** — LangGraph + Anthropic structured tool calling
already does this.

### Use case 2 — synonym normalisation

The TfL warehouse uses `line_id="elizabeth"`, but users will say
*"Lizzy line"*, *"Elizabeth line"*, *"Liz line"*. The LLM might
hallucinate `line_id="lizzy"` and the SQL returns `[]`. A
Pydantic AI sub-call could normalise:

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class LineId(BaseModel):
    line_id: Literal["bakerloo", "central", "circle", "district",
                     "hammersmith-city", "jubilee", "metropolitan",
                     "northern", "piccadilly", "victoria",
                     "waterloo-city", "elizabeth"]

normaliser = Agent(
    "anthropic:claude-haiku-4-...",
    output_type=LineId,
    instructions="Map the user's line name to the canonical line_id.",
)
```

Run inside the `query_line_reliability` tool *before* the SQL call
when the LLM-supplied `line_id` is not in the literal set. Pydantic
AI's `Agent.run(...)` does the schema-constrained extraction in a
sub-second Haiku call.

### Use case 3 — operational vs strategic intent classification

If we adopt the Haiku-router topology (§3 Option B, rejected), we'd
need a typed classifier. With `create_react_agent` (Option A), the
Sonnet model handles intent implicitly. **Skip.**

### Recommendation for plan §2

Take **use case 2** (line-id normaliser). It is a small, testable
function with a clear "Pydantic AI earns its place" rationale. Skip
use case 1 (LangGraph already does it) and use case 3 (would
overload Pydantic AI with topology decisions LangGraph handles).

The normaliser sits in `src/api/agent/extraction.py`. Tested via a
fake Pydantic AI `TestModel` (per Pydantic AI docs at
`/pydantic/pydantic-ai`).

LangSmith picks up Pydantic AI traces automatically when
`LANGSMITH_*` env vars are set (CLAUDE.md §"Observability"). No new
wiring.

## 7. Routing and model selection

CLAUDE.md tech-stack: *"Anthropic Claude (Haiku for routing, Sonnet
for final answer)"*. With the `create_react_agent` topology adopted
in §3, **Sonnet alone runs the loop** for v1, while Haiku is reserved
for the Pydantic-AI line-id normaliser (§6). Trade-off:

| Aspect | Sonnet-only loop | Haiku→Sonnet split |
|---|---|---|
| Tokens | ~3× higher per turn | Cheaper |
| Tool-call accuracy | Better (Sonnet > Haiku) | Marginally worse |
| Code lines | ~30 | ~80–120 |
| LangSmith readability | One trace per turn | Two traces per turn |

Cost: Sonnet 3.5 ≈ $3 in / $15 out per 1M tokens. A typical chat
turn is ~1k in / ~400 out → ~$0.009/turn. Portfolio traffic (single-digit
queries/day) → ~$0.30/month worst case. Acceptable.

### System prompt sketch

```
You are tfl-monitor's London transport assistant. The user asks
about TfL operations or strategy. You have these tools:

- query_tube_status: live status of every line right now
- query_line_reliability: reliability for a single line over a
  window (default 7 days)
- query_recent_disruptions: most recent disruptions, optionally
  scoped to a mode (tube, bus, dlr, ...)
- query_bus_punctuality: punctuality proxy for a single bus stop.
  Note: this is a proxy on prediction freshness, not a ground-truth
  on-time KPI. Cite that caveat in your answer.
- search_tfl_docs: retrieve passages from TfL strategy docs
  (Business Plan, Mayor's Transport Strategy, Annual Report). Use
  this for policy / strategy / forecast questions.

Pick the smallest set of tools that answers the question. When you
quote a strategy doc, cite the document title and page number from
the snippet metadata. Today's date is {today}.
```

`{today}` resolved at request time, not bake-in.

### Models

- Routing/synth: `claude-3-5-sonnet-latest` via
  `langchain_anthropic.ChatAnthropic(model_name=..., temperature=0)`.
- Pydantic AI normaliser: `anthropic:claude-3-5-haiku-latest`. Both
  Anthropic SDK clients pick up `ANTHROPIC_API_KEY` from env.

## 8. SSE streaming

`sse-starlette 3.3.4` is in the lock. `EventSourceResponse` accepts
an async generator yielding dicts (`{"data": ..., "event": ..., "id":
...}`) or `ServerSentEvent` instances; `data` may be a JSON string
or a dict (sse-starlette serialises). Per context7
(`/sysid/sse-starlette`):

- `ping=15` (default 15 s) keeps the connection alive on idle
  proxies (Railway / Vercel both close idle TCP at ~60 s).
- `await request.is_disconnected()` polled inside the generator
  short-circuits the loop when the client closes; combined with
  `asyncio.CancelledError` handling.
- `send_timeout=` per-event safety.

### Mapping LangGraph events → SSE frames

```python
async def event_stream(request: Request, body: ChatRequest):
    config = {"configurable": {"thread_id": body.thread_id}}
    inputs = {"messages": [{"role": "user", "content": body.message}]}
    try:
        async for mode, payload in agent.astream(
            inputs, config=config, stream_mode=["messages", "updates"]
        ):
            if await request.is_disconnected():
                break
            frame = _frame_from(mode, payload)   # see below
            if frame is None:
                continue
            yield {"data": json.dumps(frame)}
        yield {"data": json.dumps({"type": "end", "content": ""})}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logfire.exception("chat.stream.failed", thread_id=body.thread_id)
        yield {"data": json.dumps({"type": "end", "content": "error"})}
```

`_frame_from` rules:

| `(mode, payload)` | Emit |
|---|---|
| `("messages", (chunk, _meta))` where chunk has token text | `{"type": "token", "content": chunk.content}` |
| `("updates", {"tools": {...}})` (a tool node ran) | `{"type": "tool", "content": <tool_name_extracted>}` |
| anything else | drop |

The LLM emits AIMessage chunks with `content` being a list of text
blocks (Anthropic content-block convention). We extract by
concatenating any `text`-typed blocks. (Context7 confirms this is the
Anthropic+LangChain shape.)

### `text/event-stream` content-type

`EventSourceResponse` sets the right content-type and disables
buffering. FastAPI's OpenAPI generator will not introspect the
shape; we keep `response_model=None` on the route. The hand-written
OpenAPI YAML's `text/event-stream` description remains the contract
of record.

### Persistence on first user message

The handler must persist the user's message *before* streaming
starts, so a client that re-issues `GET /history` mid-stream sees
the user turn. The assistant turn lands at stream end (after
`"type":"end"`). See §9 for the persistence layer.

### Background-task safety

We never schedule a `BackgroundTask` after streaming starts —
sse-starlette + LangGraph `astream` is the whole story. No `asyncio.create_task`
fire-and-forget. Pool-checkout happens inside each tool call; tools
run on the same event loop as the SSE generator, so the connection
release is deterministic.

## 9. Thread persistence

Two questions: (a) where does LangGraph keep its checkpoints and (b)
where do we store the `ChatMessage[]` returned by `/history`? They
are not necessarily the same.

### LangGraph checkpointer choice

Three serialisation backends:

| Backend | Persistence | Setup | Footprint |
|---|---|---|---|
| `InMemorySaver` (built-in) | In-process, lost on restart | 1 line | 0 deps, 0 SQL |
| `langgraph-checkpoint-sqlite` | One SQLite file (`*.db`) | `pip install` | 1 file |
| `langgraph-checkpoint-postgres` | Tables in the warehouse | `pip install`, schema migration | 4 tables |

For a portfolio with no chat history retention requirement,
`InMemorySaver` is ostensibly enough. But:

- `/history` becomes useless after a restart (every thread vanishes).
- `thread_id` collisions across restarts produce confusing dialogue.
- Demo recording: a reviewer reloads the page mid-conversation.

### Storage of the canonical `ChatMessage[]` for `/history`

Three options:

#### A. Use the LangGraph Postgres checkpointer as the source of truth.

`AsyncPostgresSaver` stores `messages` per thread in JSONB. `/history`
loads the latest checkpoint and projects to `ChatMessage[]`.

- **Pros**: one storage; LangGraph already manages the lifecycle.
- **Cons**: schema is LangGraph-internal (4 tables: `checkpoints`,
  `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`);
  reading `messages` from a checkpoint requires deserialising
  `AnyMessage` objects (LangChain) and mapping `role` to OpenAPI's
  enum. Doable but adds a tight coupling between API surface and
  LangGraph internals.

#### B. Use `InMemorySaver` for LangGraph + a small `chat_messages` table for `/history`.

Tablespec:

```sql
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.chat_messages (
    id           BIGSERIAL PRIMARY KEY,
    thread_id    TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created
    ON analytics.chat_messages (thread_id, created_at);
```

- **Pros**: decouples API from LangGraph internals; trivial SQL for
  `/history`; the same fetch helper pattern as TM-D2/D3.
- **Cons**: two persistence layers (in-memory checkpoint, SQL log).
  In-memory checkpoint lost on restart, but `/history` survives — a
  user reloading post-restart sees their messages but a follow-up
  message starts a fresh agent thread (no working memory of prior
  tool calls). Acceptable for a portfolio.

#### C. Use the Postgres checkpointer **plus** a thin `chat_messages` table.

Both — the checkpointer for in-flight state, the SQL log for
`/history`. Fully bullet-proof but doubles the writes.

### Migration approach

Per ADR 002 (contracts-first): table DDL goes in
`contracts/sql/004_chat.sql`. Same idempotent pattern as
`001_raw_tables.sql` (`CREATE SCHEMA IF NOT EXISTS analytics`,
`CREATE TABLE IF NOT EXISTS …`). No Alembic.

But: track scope (CLAUDE.md §"WP scope rules" #2) says "a WP touches
only directories in its track". `D-api-agent` and `contracts/`
intersect at *contracts/openapi.yaml* (which we don't touch); a new
`contracts/sql/004_chat.sql` is a contract change. **Phase 2 must
decide whether this is a track violation** or whether it falls under
the same exemption that ADR 002 §"Consequences" describes ("contract
changes are heavier — they force ADRs"). My read: 004 is a
non-breaking additive schema, and TM-D5 owns the chat surface, so the
edit is in-scope. Plan §2 must lock this.

### Recommendation for plan §2

**Option B** — `InMemorySaver` for LangGraph + a `analytics.chat_messages`
table for `/history`. Reasons:

1. Lean (Principle #1): one extra dep beats four-table migration.
2. Decouples `/history` from LangGraph internals.
3. The "agent forgets after restart" caveat is a portfolio-acceptable
   trade-off, called out in plan §4.

Add `contracts/sql/004_chat.sql` and `dbt/sources/tfl.yml` is
**not** touched (the table is API-owned, not source data). dbt does
not need to read chat messages. This keeps the cross-track edits to
exactly two files (`004_chat.sql` and the API code).

Persistence helpers live next to the SQL helpers in `src/api/db.py`
or a new `src/api/agent/history.py` (decision in plan §2).

## 10. Observability split (already an ADR)

Direct mapping:

| Span / trace | Tool | Configured by |
|---|---|---|
| `POST /chat/stream` request span | Logfire (FastAPI auto) | `instrument_fastapi(app)` already on. |
| `psycopg` query inside a tool | Logfire (psycopg auto) | `instrument_psycopg("psycopg")` already on. |
| Pinecone HTTP latency | Logfire (httpx auto) | `instrument_httpx()` already on; LlamaIndex routes through httpx. |
| LangGraph node execution | LangSmith | `LANGSMITH_TRACING=true` env. |
| Each tool call (start/end + args/result) | LangSmith (auto) | Same. |
| Anthropic LLM call (tokens, model, latency) | LangSmith (auto) | Same. |
| Pydantic AI extraction | LangSmith (auto) | Same. |
| Retrieval chunks (which docs were pulled) | LangSmith (auto) | Same. |

**No custom metrics** (CLAUDE.md §"Anti-patterns to avoid"). The
SSE generator gets a single `logfire.span("chat.stream", thread_id=..., message_chars=len(...))`
wrapper to bound the request — that is already given to us by the
FastAPI auto-instrument and does not need duplicating.

## 11. Security considerations

### SQL safety

- All five SQL tools route through TM-D2/D3 fetchers, which
  already use `%(name)s` named parameters. The agent cannot
  interpolate.
- Tool argument types are Pydantic models; the LLM cannot smuggle
  in a SQL fragment because the field types reject it before psycopg
  ever sees the input (`window_days: int = Field(ge=1, le=90)`).

### Tool allow-list

The LLM only ever sees five tools (the catalogue in §4 + §5). No
"exec_sql", no shell, no HTTP fetch. The LangGraph
`create_react_agent` only binds the tools we pass.

### Input length cap

OpenAPI declares `ChatRequest.message: maxLength=4000`. FastAPI
enforces this from the spec via Pydantic; rejection is a default 422.
We do not also re-validate inside the handler — Pydantic v2 already
does it, and double-validation is a YAGNI.

### Output sanitation

The LLM streams text directly to the client. No HTML escaping
needed (response is JSON; the client renders it in shadcn-ui's
`Markdown` component). RAG snippets are quoted text from public TfL
PDFs — no PII risk.

### Prompt injection (RAG)

A retrieved chunk *is* free text and could in theory contain
`Ignore previous instructions; …`. The TfL strategy PDFs are
trusted publications and the system prompt instructs the model not to
follow instructions inside cited content. **We do not ship a custom
detector.** This risk is acknowledged in plan §4 ("What we are NOT
doing") with a note that, were the corpus to expand to user-uploaded
PDFs, a detector would become required.

### CORS

Allowlist unchanged (`http://localhost:3000`,
`https://tfl-monitor.vercel.app`). SSE works with the existing CORS
middleware (`text/event-stream` is not a preflight-triggering
content-type for `POST` with `application/json` body — the *request*
is JSON; the response is the streamed event-stream).

### Bandit gate

`uv run bandit -r src --severity-level high` must report zero
findings. The new code is async I/O + httpx + psycopg — none of
which trips HIGH-severity rules. Watch for:

- B608 (SQL injection) — no f-strings around params: use TM-D2/D3
  fetchers verbatim.
- B105/B106 (hardcoded password) — `SecretStr` for
  `ANTHROPIC_API_KEY` per §12.

## 12. Configuration and secrets

### Env vars (all already in `.env.example`)

| Var | Purpose | Already in env? |
|---|---|---|
| `DATABASE_URL` | Existing pool DSN. | Yes (TM-D2). |
| `ANTHROPIC_API_KEY` | Sonnet + Haiku. | Yes (`.env.example` line 20). |
| `OPENAI_API_KEY` | Embedding queries via LlamaIndex `OpenAIEmbedding`. | Yes (TM-D4). |
| `PINECONE_API_KEY` | Pinecone client. | Yes (TM-D4). |
| `PINECONE_INDEX` | Defaults to `tfl-strategy-docs`. | Yes (TM-D4). |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | LangGraph + Pydantic AI auto-tracing. | Yes (TM-D1). |
| `LOGFIRE_TOKEN` | Logfire auto. | Yes (TM-D1). |

**No new env var** is needed. Plan §2 to lock that explicitly.

### Lifespan additions

`src/api/main.py` already opens an `AsyncConnectionPool` in lifespan
when `DATABASE_URL` is set. TM-D5 adds:

- Compile the LangGraph agent once at startup, attach to
  `app.state.agent`.
- If `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `PINECONE_API_KEY`
  is missing → set `app.state.agent = None` and log
  `chat_disabled_no_credentials`. Handlers return **503** RFC 7807
  (mirrors the existing pool-missing pattern).
- If `DATABASE_URL` is missing, the agent still compiles (search
  works against Pinecone), but every SQL tool returns *"Database
  unavailable"*; alternatively we mark the agent unavailable
  altogether. Lean: degrade — agent stays usable for strategy
  questions even without the warehouse. **Plan §2 to confirm.**

### Settings model

CLAUDE.md Principle #1 rule 5: "no nested `BaseSettings` unless ≥15
variables". We have ≤7 here for the agent piece (and most are read
by other services). **Skip a new settings class.** Read env directly
via `os.environ.get(...)` at lifespan time, propagate through
function args. (TM-D2's lifespan does this for `DATABASE_URL`
already.)

### Graceful degradation matrix

| Missing | `/health` | `/status/*`, `/reliability`, `/disruptions/*`, `/bus/*` | `/chat/stream` | `/chat/{tid}/history` |
|---|---|---|---|---|
| `DATABASE_URL` | ok | 503 | 503 (lean) or RAG-only (alt) | 503 |
| `ANTHROPIC_API_KEY` | ok | unaffected | 503 | unaffected (history is just SQL) |
| `OPENAI_API_KEY` | ok | unaffected | 503 (no retrieval) | unaffected |
| `PINECONE_API_KEY` | ok | unaffected | 503 | unaffected |
| `LANGSMITH_*` unset | ok | unaffected | ok (no tracing) | ok |
| `LOGFIRE_TOKEN` unset | ok | unaffected | ok (no tracing) | ok |

History is independently usable — only needs `DATABASE_URL`.

## 13. Test strategy

Three tiers, mirroring TM-D2/D3.

### Unit (default `uv run task test`)

New folder: `tests/agent/`.

| File | Cases |
|---|---|
| `tests/agent/test_extraction.py` | Pydantic AI normaliser maps "Lizzy" → `elizabeth`, "Lizzie" → `elizabeth`, unknown → keeps input. Uses `pydantic_ai.models.test.TestModel` (the framework's official fake) so no Haiku call leaves the test boundary. |
| `tests/agent/test_sql_tools.py` | Each of the four SQL tools, called with a `FakeAsyncPool`, returns the fetcher's typed Pydantic output verbatim. Argument validation: out-of-range `window_days` raises before SQL fires. |
| `tests/agent/test_rag_tool.py` | `search_tfl_docs` against a fake `PineconeVectorStore` (LlamaIndex exposes `MockVectorStore`-pattern via `from_documents([...])` — easier: hand-roll a fake index returning canned `NodeWithScore`s). Asserts that fan-out queries each namespace when `doc_id` is None, and a single namespace when `doc_id` is provided. |
| `tests/agent/test_graph_compile.py` | Graph compiles without an Anthropic key (use a `FakeListChatModel` from `langchain-core` or `init_chat_model("openai:gpt-4o", ...)` swapped with a stub). Smoke: agent.invoke({"messages":[...]}) returns within `n` ticks. |
| `tests/api/test_chat_history.py` | `GET /api/v1/chat/{tid}/history` happy path (returns Pydantic-validated rows from `analytics.chat_messages` via `FakeAsyncPool`); 404 when no rows; 503 when pool missing. |
| `tests/api/test_chat_stream.py` | `POST /api/v1/chat/stream` via `TestClient` with the agent compiled around a `FakeListChatModel` returning a deterministic AIMessage; assert SSE frames in order: ≥1 `token`, optional `tool`, final `end`; assert input persistence side-effect (one row written to fake pool with role=user, one with role=assistant). |
| `tests/api/test_stubs.py` | Drop the two TM-D5 rows from `STUB_ROUTES`. Bidirectional drift checks must pass. |

### Drift / contract

Same as TM-D2/D3.

### Integration (`-m integration`, gated on env)

Three new files under `tests/integration/`:

- `tests/integration/test_chat_history.py` — gated on
  `DATABASE_URL`. `_ensure_table(cur)` creates
  `analytics.chat_messages` if absent (mirrors D2/D3 helpers).
  Insert two rows; hit the endpoint; assert ordering.
- `tests/integration/test_chat_stream.py` — gated on the four-key
  combo (`DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `PINECONE_API_KEY`). Hits the real endpoint with a deterministic
  prompt; reads SSE frames; asserts terminal `type:"end"` and
  non-empty token stream. Marked `@pytest.mark.slow` — runs only on
  request because it spends real Anthropic tokens.
- `tests/integration/test_chat_history_after_stream.py` — chains the
  above two: stream a turn, then `GET /history`, assert two rows
  back. Same env gates.

### Fixtures

`tests/conftest.py` already defines `FakeAsyncPool`, `fake_pool_factory`,
`attach_pool`. Reusable as-is. We add:

- `tests/agent/conftest.py` — `FakeAnthropic` and `FakePineconeIndex`
  helpers + a fixture that constructs a fresh agent graph wired to
  fakes, so every test in `tests/agent/` gets a hermetic agent.
- `pytest.fixture` for `attach_agent` (mirrors `attach_pool`):
  monkeypatches `app.state.agent` and restores on teardown.

## 14. Risks / surprises

1. **Missing chat-related deps** (§1.5). Plan must add
   `langchain-anthropic`, `llama-index-vector-stores-pinecone`. We do
   not need a checkpointer backend dep if we stick with
   `InMemorySaver` (§9 Option B). Add `langchain-core` only as a
   transitive (already present 1.3.0).
2. **Pool contention** (§4 Option B). Agent tool calls share the
   `min=1, max=4` pool with the dashboard. A long-running tool chain
   could hold connections through Sonnet's response. Mitigation:
   tools acquire-and-release per query (`async with pool.connection()
   as conn` already does this); consider `pool.timeout=10` to bail
   early.
3. **SSE on slow proxies / Vercel.** Vercel terminates idle
   connections after ~10s on the Hobby plan; sse-starlette `ping=15`
   needs to be tuned to ≤9 if the production deploy targets Vercel.
   Plan §2 should default `ping=15` (the Railway backend) and add a
   note to revisit at TM-A5.
4. **Backwards-incompatible `astream_events`.** Earlier LangGraph
   docs reference `astream_events(version="v2")`. v1.x prefers
   `astream(stream_mode=...)`. Plan locks the new API.
5. **`MessagesState` ID stability.** `add_messages` reducer
   deduplicates by `id`. If the user posts twice with the same UUID
   client-side, the second message is dropped. We never set ids
   client-side — LangChain auto-generates. Note this in plan §9 to
   prevent future drift.
6. **Pydantic AI version churn.** Two pydantic-ai versions appear
   in `uv.lock` (1.75.0 and 1.85.0). The lock resolves to the
   higher one when explicitly imported; the older is a transitive
   pin. Lean: import from the package, let uv resolve. Ensure
   `pyproject.toml` constraint `pydantic-ai>=0.0.14` (current) is
   broad enough — yes.
7. **`/history` empty thread**: should it 404 (per OpenAPI declared
   404 response) or return `[]`? Lean: **404** if `thread_id` was
   never seen by `/chat/stream`; **`200 []`** if seen with no
   messages (impossible by construction — every stream call writes
   ≥1 row). Decision in plan §2.
8. **Cross-track edit on `contracts/sql/004_chat.sql`** (§9).
   Documented exception or stop-and-ask. Plan must lock.
9. **Token streaming fidelity.** Anthropic's content blocks include
   text chunks but also `thinking`, `tool_use`, `tool_result`
   blocks. Our token frame must filter to `text`-typed content,
   else the client renders raw JSON tool args mid-stream.
10. **`stream_mode="messages"` chunk semantics.** Each yielded chunk
    is `(message_chunk, metadata)` where `message_chunk` is an
    `AIMessageChunk` (LangChain). `metadata.langgraph_node` tells
    us which node produced the chunk; we filter to the
    "agent"/"router" node so tool-step internal chatter doesn't leak.
11. **Empty `content` in tool-call AIMessageChunks.** When the model
    is composing a tool call, the chunk's `.content` may be `[]`
    while `.tool_call_chunks` is populated. We skip these in the
    SSE projection so we don't emit empty `token` frames.
12. **Concurrent thread updates.** Two clients posting to the same
    `thread_id` simultaneously is undefined (LangGraph
    `InMemorySaver` is single-process; concurrent writes to
    `chat_messages` race on `BIGSERIAL id`, which is fine, but
    `/history` ordering can interleave). Lean: not solved for v1.
    Note in plan §4.

## 15. Open questions for Phase 2

Numbered. Every one must resolve in the plan.

1. **Graph topology.** `create_react_agent` (Option A) vs. hand-rolled
   `StateGraph` (Option B). Lean: A.
2. **Single-model vs. Haiku→Sonnet.** Lean: Sonnet only for v1; Haiku
   only inside the line-id normaliser (Pydantic AI).
3. **SQL tools call HTTP self vs. fetcher direct.** Lean: fetcher
   direct (§4 Option B).
4. **RAG fan-out.** Per-namespace fan-out + optional `doc_id` filter
   (§5 Options A + C).
5. **Pydantic AI scope.** Use it for the line-id normaliser only.
   Skip it for graph routing.
6. **LangGraph checkpointer.** `InMemorySaver` (§9 Option B).
7. **Chat history persistence.** New
   `analytics.chat_messages` table via
   `contracts/sql/004_chat.sql` (§9).
8. **Cross-track edit on `contracts/sql/`.** Treated as in-scope per
   ADR 002 §"Consequences"; documented in PR body. Lean: in-scope.
9. **Agent compile dependency on env.** `app.state.agent = None`
   when any of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `PINECONE_API_KEY` is missing → 503 from `/chat/stream`
   (mirrors pool-missing). `/chat/{tid}/history` independent —
   only needs `DATABASE_URL`.
10. **Module layout.** `src/api/agent/` package with sub-modules
    (`graph.py`, `tools.py`, `extraction.py`, `prompts.py`,
    `history.py`, `streaming.py`) vs. flat append to `src/api/main.py`.
    Lean: package — chat surface is too large for inline. ~400–600 LoC.
11. **`/chat/{tid}/history` 404 vs `[]`.** Lean: **404** when no
    rows, RFC 7807 problem.
12. **SSE `ping` interval.** Default `15` s (sse-starlette default,
    fits Railway). Note Vercel-side adjustment for TM-E4.
13. **Tool catalogue completeness.** Five tools (4 SQL + 1 RAG). No
    HTTP-fetch / open-ended SQL. Lean: confirm.
14. **System prompt ownership.** A single string constant in
    `src/api/agent/prompts.py`. Sub-1k tokens, no template engine.
15. **Bandit findings expectation.** Zero HIGH. Same gate as TM-D2/D3.

## 16. Files expected to change in Phase 3

Authoritative list (subject to plan refinement):

New:

- `src/api/agent/__init__.py`
- `src/api/agent/graph.py` (compile the LangGraph agent)
- `src/api/agent/tools.py` (5 tools + Pydantic input schemas)
- `src/api/agent/extraction.py` (Pydantic AI line-id normaliser)
- `src/api/agent/prompts.py` (system prompt constant)
- `src/api/agent/streaming.py` (`_frame_from`, SSE helpers)
- `src/api/agent/history.py` (chat_messages CRUD)
- `contracts/sql/004_chat.sql` (analytics.chat_messages DDL)
- `tests/agent/__init__.py`
- `tests/agent/conftest.py`
- `tests/agent/test_extraction.py`
- `tests/agent/test_sql_tools.py`
- `tests/agent/test_rag_tool.py`
- `tests/agent/test_graph_compile.py`
- `tests/api/test_chat_history.py`
- `tests/api/test_chat_stream.py`
- `tests/integration/test_chat_history.py`
- `tests/integration/test_chat_stream.py`
- `tests/integration/test_chat_history_after_stream.py`

Modified:

- `pyproject.toml` (add `langchain-anthropic`,
  `llama-index-vector-stores-pinecone`)
- `uv.lock` (regenerated)
- `src/api/main.py` (lifespan compiles + caches agent;
  `post_chat_stream` and `get_chat_history` handlers wired)
- `src/api/db.py` — only if `history.py` lives there; otherwise
  untouched
- `tests/api/test_stubs.py` (drop two TM-D5 rows)
- `PROGRESS.md` (TM-D5 row → ✅)

Untouched:

- `contracts/openapi.yaml` (frozen).
- `contracts/schemas/*` (Kafka tier).
- `dbt/` (no chat-mart needed).
- `web/` (TM-E3 owns chat UI).
- `src/ingestion/` (B-ingestion track).
- `src/rag/` (D4 owned, agent only consumes).
- `airflow/`.
- `Makefile`, `docker-compose.yml`.
