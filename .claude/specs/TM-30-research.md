# TM-30 (PR-C) — Research

**WP:** journey planning + arrivals tools for the Bedrock agent (GitHub issue #103).
**Phase:** 1 — Research (read-only). No design decisions here; see `TM-30-plan.md`.
**Dependency:** PR-B / TM-29 (station resolver) — **merged** (`170212c`), so `analytics.dim_stations` + `src/api/stations.py` exist.
**Master plan:** `~/.claude/plans/quiet-humming-kay.md` → PR-C.

---

## Scope (from the issue)

1. `TflClient.plan_journey(...)` → `/Journey/JourneyResults/{from}/to/{to}`.
2. New tier-1 contracts: `TflJourneyResult`, `TflJourneyLeg` (arrivals model already exists).
3. Two LangGraph tools in `src/api/agent/tools.py`: `plan_journey_tool`, `get_arrivals_tool`.
4. Agent prompt guidance for both tools.
5. Frontend chat quick-prompt chips.
6. Tests across TfL client + agent tools.

---

## Existing code map

### `src/ingestion/tfl_client/client.py`

- **`__init__`** (41–59): `TflClient(app_key, *, base_url="https://api.tfl.gov.uk", timeout=30.0, max_attempts=3, transport=None)`. httpx client is `None` until `__aenter__` (async context manager).
- **`_request`** (127–147): `async def _request(self, path, *, params=None) -> Any`. Injects `app_key` into params (`{**(params or {}), "app_key": self._app_key}`), calls `self._http.get(path, params=outbound)`, wrapped in `with_retry(_call, max_attempts=self._max_attempts)` (from `ingestion.tfl_client.retry`).
- **`fetch_arrivals(stop_id)`** (91–96): EXISTS. `async def fetch_arrivals(self, stop_id) -> list[TflArrivalPrediction]`. Hits `/StopPoint/{stop_id}/Arrivals`, validates via `_ARRIVAL_ADAPTER` (`TypeAdapter`).
- **`fetch_stop_point(naptan_id)`** (98–109): EXISTS (PR-B). Returns a `TflStopPoint`; used by the reverse resolver.
- **Journey planning: DOES NOT EXIST.** No `plan_journey`, no `/Journey/JourneyResults`. **Gap to build.**
- **House style:** every method returns parsed tier-1 Pydantic models (via `TypeAdapter`/`model_validate`), never raw JSON.

### `contracts/schemas/tfl_api.py`

- Tier-1 models, all `frozen=True`. Shared config `_tfl_model_config()` (21–27): `alias_generator=to_camel`, `populate_by_name=True`, `extra="ignore"`, `frozen=True`.
- Existing models: `TflValidityPeriod`, `TflLineStatusDisruption`, `TflLineStatusItem`, `TflLineResponse`, `TflStopPoint`, **`TflArrivalPrediction`** (97–114).
- `TflArrivalPrediction` fields: `id`, `naptan_id`, `station_name`, `line_id`, `line_name`, `platform_name`, `direction?`, `destination_name?`, `expected_arrival: datetime`, `time_to_station: int (ge=0)`, `vehicle_id?`, `mode_name`.
- **`TflJourneyResult` / `TflJourneyLeg`: DO NOT EXIST.** New models must reuse `_tfl_model_config()` (camelCase aliasing, frozen).

### `src/api/stations.py` (PR-B)

- **`resolve_naptans`** (59–101): `async def resolve_naptans(*, pool: AsyncConnectionPool, tfl_client: TflClient | None, naptan_ids: Iterable[str]) -> dict[str, str | None]`. Batch reverse lookup (NaPTAN → name). Fast path = `analytics.dim_stations`; fallback = `tfl_client.fetch_stop_point(nid).common_name`.
- Module globals: `_NAPTAN_CACHE: dict[str, str | None]` (caches confirmed 404s as `None`, lets transient failures retry), `_TFL_SEMAPHORE` to bound concurrent TfL calls.
- Dependencies are **injected** (pool + optional `TflClient`), no singleton.
- **Forward lookup (name → NaPTAN): DOES NOT EXIST.** No `resolve_name`, no `search_stop`, no `/StopPoint/Search`. The master plan assumes `api.stations.resolve_name(query)` — **this is a gap.** Journey + arrivals tools accept free-text station names, so forward resolution must be built (new `TflClient` search method + a `stations.py` forward resolver, or equivalent).

### `src/api/agent/tools.py`

- Tools defined with LangChain `@tool` (and `@tool(args_schema=PydanticModel)` when a schema is wanted), inside a factory `make_tools(*, pool: AsyncConnectionPool, retriever: VectorStoreIndex | None = None) -> list[BaseTool]`.
- Dependencies captured by **closure** from `make_tools` args. **`make_tools` does NOT currently receive a `TflClient`** — the new tools need one, so the factory signature (and its call site in `graph.py`) must grow a `tfl_client` param.
- Each tool wraps work in `logfire.span("agent.tool.<name>")`; SQL tools call `fetch_*` from `src/api/db.py` and `r.model_dump(mode="json")`.
- Free-text → canonical extraction uses Pydantic AI Haiku: `normalise_line_id(text) -> str | None` in `src/api/agent/extraction.py` (72–96), output model `LineId` (44–47). Pattern: `Agent(model_string, output_type=..., instructions=...)`, swallow exceptions → `None`.
- Registered tools (164–194): `query_tube_status`, `query_line_reliability`, `query_recent_disruptions`, `query_bus_punctuality`, `search_tfl_docs` (only when retriever present).

### `src/api/agent/graph.py`

- **`compile_agent(*, pool, model=None)`** (95–127): builds chat model (`_build_chat_model`: Bedrock `ChatBedrockConverse` when `BEDROCK_REGION` set, else `ChatAnthropic` when `ANTHROPIC_API_KEY` set, else `None` → chat 503), builds retriever, `tools = make_tools(pool=pool, retriever=retriever)`, returns `create_react_agent(model=..., tools=tools, prompt=render(), checkpointer=InMemorySaver())`.
- Agent compiled once in FastAPI lifespan, cached on `app.state.agent`.
- Adding a tool = define in `make_tools`, append to the returned list. Injecting `TflClient` = thread it from lifespan (`app.state.tfl_client` already exists per PR-B) → `compile_agent` → `make_tools`.

### `src/api/agent/prompts.py`

- System prompt (7–21) lists each tool with a one-line description; ends with "Pick the smallest tool set that answers. Today is {today}." `render(today=None)` substitutes `{today}`. Two new tool lines slot into the existing list.

### `web/components/dashboard/chat-panel.tsx`

- Input state: `const [value, setValue] = useState("")` (48). `send()` trims, guards `inFlightRef`, clears via `setValue("")` (80), streams via `streamChat()`.
- **Quick-prompt chips ALREADY EXIST**: `DEFAULT_QUICK_PROMPTS` (31–38) with current chips `Next train` / `Why delayed?` / `Ticket acceptance`; rendered 244–254 as `.tfl-chip-sm` buttons calling `onClick={() => setValue(prompt.value)}`, `disabled={busy}`. **TM-30 only updates the chip set** (issue wants "Plan a journey", "Next arrivals at…", "Status of [line]") — the chip infrastructure is done.

---

## Test patterns

- **TfL client** (`tests/ingestion/`): inject `transport=httpx.MockTransport(handler)` into `TflClient`; `handler(request) -> httpx.Response`. No respx.
- **Pydantic AI extraction** (`tests/agent/test_extraction.py`): `agent.override(model=TestModel(custom_output_args={...}))` from `pydantic_ai.models.test`.
- **Agent compile** (`tests/agent/conftest.py`): `FakeChatModel`, `FakeRetriever`, `FakeIndex` injected via `compile_agent(model=FakeChatModel(), ...)` so tests never hit Anthropic/Bedrock.

---

## Assumption-vs-reality table

| Master-plan assumption | Reality |
|---|---|
| `fetch_arrivals(stop_id)` exists | ✓ `client.py:91` |
| `TflArrivalPrediction` exists | ✓ `tfl_api.py:97` |
| `resolve_naptan` reverse resolver exists | ✓ as `resolve_naptans` (batch) `stations.py:59` |
| `api.stations.resolve_name(query)` forward lookup exists | ✗ **GAP — must build** |
| `TflClient.plan_journey(...)` / journey endpoint | ✗ **GAP — must build** |
| `make_tools` can reach a `TflClient` | ✗ factory takes only `pool`+`retriever` — **must thread `tfl_client`** |
| Frontend chip infra | ✓ already wired; only chip content changes |

---

## Cross-cutting constraints (from CLAUDE.md + napkin)

- **One WP, one PR.** PR-C touches `src/ingestion/`, `contracts/schemas/tfl_api.py`, `src/api/agent/`, `src/api/stations.py`, `web/components/dashboard/chat-panel.tsx`, tests. Touching `contracts/` is in-scope for this WP (tier-1 schema append) but is a contracts-first change — may warrant an ADR per ADR 002 if the public API surface changes (journey/arrivals are agent-internal, not new REST endpoints, so likely no OpenAPI drift — confirm in plan).
- **pgbouncer cast rule** (napkin Domain #1): only relevant if new tools add SQL with NULL-comparable params. Journey/arrivals are TfL-API-backed, not SQL — likely N/A; the forward resolver's `dim_stations` query (if added) must follow the `%(p)s::text` rule.
- Bedrock is the prod LLM (`ChatBedrockConverse`); local dev uses `ChatAnthropic`. New tools are model-agnostic.
- Verification gate: `uv run task lint && uv run task test && uv run bandit -r src --severity-level high && make check`.
