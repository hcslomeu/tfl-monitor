# TM-30 (PR-C) — Plan

**WP:** journey planning + arrivals tools for the Bedrock agent (GitHub issue #103).
**Phase:** 2 — Plan. Source of truth for Phase 3.
**Research:** `.claude/specs/TM-30-research.md`. **Master plan:** `~/.claude/plans/quiet-humming-kay.md` → PR-C.
**Branch:** `feature/TM-30-journey-arrivals-tools`.

---

## Resolved design decisions (Phase 2)

| Question | Decision | Rationale |
|---|---|---|
| Name → NaPTAN resolution | Build **one general `resolve_name`** forward resolver, use it in BOTH tools | We resolve names to NaPTAN ourselves, so `/Journey/JourneyResults` receives ids (no TfL HTTP 300 disambiguation); arrivals needs an id regardless. |
| Pydantic AI extraction layer | **Skip** | TfL `/StopPoint/Search` is fuzzy-tolerant and the `@tool` `args_schema` already extracts args; a Haiku call would fire on every invocation even for correct names. YAGNI. |
| Tool return shape | **Compact typed JSON** (`model_dump`-style dict/list, trimmed to relevant fields); the agent narrates it as text | Matches the house style of the existing tools; keeps context lean; reaches the UI as normal text tokens with zero streaming changes. |
| Rich journey rendering in chat | **Out of scope** — deferred to a follow-up WP | The stream deliberately suppresses tool results (`streaming.py:38-49`) and the `Frame` union is string-only (`sse-parser.ts`). Rich `<JourneyCard>` needs a new structured SSE frame + parser + interception — a cross-layer change that would burst "one WP, one PR". |

---

## Implementation phases

Run `uv run task lint && uv run task test` after each backend phase; `pnpm --dir web lint && pnpm --dir web test` after the frontend phase. Do not proceed on red.

### Phase 1 — Contracts (`contracts/schemas/tfl_api.py`, append)

New tier-1 models, all reusing `_tfl_model_config()` (camelCase alias, `frozen=True`, `extra="ignore"`). Model the nested TfL shapes explicitly (alias generation does not reach into nested objects):

- `TflJourneyMode` — `{ name: str }` (maps `leg.mode.name`).
- `TflJourneyInstruction` — `{ summary: str }` (maps `leg.instruction.summary`).
- `TflJourneyLeg` — `{ duration: int, mode: TflJourneyMode, instruction: TflJourneyInstruction, departure_time: datetime | None = None, arrival_time: datetime | None = None }`.
- `TflJourneyResult` — `{ start_date_time: datetime, arrival_date_time: datetime, duration: int, legs: list[TflJourneyLeg] }`.
- `TflStopSearchMatch` — `{ id: str, name: str, modes: list[str] = [] }` (TfL Search match; `id` is the StopPoint/NaPTAN).
- `TflStopSearchResponse` — `{ matches: list[TflStopSearchMatch] = [] }`.

**Scope note:** `contracts/` edits in a non-TM-000 WP normally trip CLAUDE.md WP-rule #2, but the issue explicitly lists `contracts/schemas/tfl_api.py` and these are additive tier-1 ingestion DTOs (not the Kafka tier-2 schemas, not the OpenAPI public surface). No `dbt_sources.yml` mirror touched → CI diff gate unaffected. **No ADR needed** (additive, no public-contract change). Confirm no test snapshots `tfl_api.py` model count before relying on this.

**Tests:** parse a committed journey fixture + a search fixture into the models; assert nested `mode.name` / `instruction.summary` resolve.

### Phase 2 — TfL client (`src/ingestion/tfl_client/client.py`)

- `async def search_stop(self, query: str) -> TflStopSearchResponse` → `GET /StopPoint/Search/{query}` via `_request`, validate into `TflStopSearchResponse`.
- `async def plan_journey(self, from_id: str, to_id: str, *, departure_time: datetime | None = None, modes: Iterable[str] | None = None) -> list[TflJourneyResult]` → `GET /Journey/JourneyResults/{from_id}/to/{to_id}` with params: `date`/`time`/`timeIs="Departing"` when `departure_time` given (TfL format `yyyyMMdd` / `HHmm`), `mode=",".join(modes)` when given. Validate the response `journeys` array into `list[TflJourneyResult]` via `TypeAdapter`.
- Mirror the existing parsed-model return convention; reuse `_request` (auth + retry).

**Tests (`tests/ingestion/test_tfl_client_journey.py`, new):** `httpx.MockTransport` handler asserts the exact path + params for both methods; returns committed fixtures; assert parsed models. Cover `plan_journey` with and without `departure_time`/`modes`, and `search_stop` returning ≥1 match.

### Phase 3 — Forward resolver (`src/api/stations.py`)

- `async def resolve_name(*, tfl_client: TflClient | None, query: str) -> str | None` → returns a NaPTAN/StopPoint id, or `None` when unresolved/no client.
  - Calls `tfl_client.search_stop(query)`, returns `matches[0].id` (TfL ranks by relevance). When `matches` is empty → `None`.
  - Process-level cache mirroring `_NAPTAN_CACHE`: `_NAME_CACHE: dict[str, str | None]` keyed by the normalised (lowercased, stripped) query; cache `None` for confirmed no-match so repeats are free but transient failures (exception) are NOT cached (re-raise or return `None` without caching, matching the reverse-resolver's "don't poison on a hiccup" stance).
  - **No `dim_stations` DB fast-path** (deferred): TfL Search is authoritative + fuzzy and the cache covers repeat cost; adding an ILIKE query would reintroduce the pgbouncer `%(p)s::text` concern (napkin Domain #1) for marginal benefit.

**Tests (`tests/api/test_stations.py`, extend):** match found → id; no match → `None` (and cached); `tfl_client=None` → `None`; cache hit avoids a second transport call.

### Phase 4 — Agent tools + wiring

- **`src/api/agent/tools.py`**: grow factory to `make_tools(*, pool, tfl_client: TflClient | None = None, retriever=None)`. Two new tools (skip when `tfl_client is None`, same gating pattern as the retriever-gated RAG tool):
  - `plan_journey_tool(origin: str, destination: str, departure_time: str | None = None)`: `resolve_name` both endpoints; if either is `None` → return a friendly string ("Couldn't find station '<x>'."); else `tfl_client.plan_journey(...)`; return a **compact dict** of the best journey: `{ total_minutes, start, arrival, legs: [{ mode, summary, minutes }] }` (trim TfL noise). Wrap in `logfire.span("agent.tool.plan_journey_tool")`.
  - `get_arrivals_tool(stop: str)`: `resolve_name`; `tfl_client.fetch_arrivals(naptan)`; group by `platform_name`, sort each group by `time_to_station`, cap 5/platform; return `{ station, platforms: [{ platform, arrivals: [{ line, destination, seconds }] }] }`. Friendly string on unresolved stop. `logfire.span`.
- **`src/api/agent/graph.py`**: `compile_agent(*, pool, tfl_client=None, model=None)` threads `tfl_client` into `make_tools`. Read `app.state.tfl_client` (exists since PR-B) in the FastAPI lifespan and pass it to `compile_agent`.
- **`src/api/agent/prompts.py`**: add two tool lines to the existing list, e.g.:
  - `- plan_journey_tool: plan a route between two stations (names or NaPTAN). Use when the user asks how to get from A to B.`
  - `- get_arrivals_tool: next arrivals at a stop (name or NaPTAN), grouped by platform. Use for "when's the next train/bus at X".`

**Tests (`tests/agent/test_tools.py`, extend):** mock `TflClient` + fake pool + stub `resolve_name`; cover journey happy path, unresolved origin/destination, arrivals grouping + 5/platform cap, `tfl_client=None` → tools absent from `make_tools` output. **Anti-orphan check (napkin #9):** after wiring, `grep -rn "plan_journey_tool\|get_arrivals_tool" src/api/agent` must show both registered in `make_tools` AND no dead references.

### Phase 5 — Frontend chips (`web/components/dashboard/chat-panel.tsx`)

- Replace `DEFAULT_QUICK_PROMPTS` content with the issue's set (infra already wired — only `value`/`label` change):
  - `{ label: "Plan a journey", value: "Plan a journey from Oxford Circus to Bank" }`
  - `{ label: "Next arrivals", value: "Next arrivals at Bank" }`
  - `{ label: "Line status", value: "What's the status of the Central line?" }`
- Update `web/components/dashboard/__tests__/chat-panel.test.tsx` chip assertions to the new labels/values; confirm clicking a chip pre-fills the textarea.

### Phase 6 — Verification + PR

- Gate: `uv run task lint && uv run task test && uv run bandit -r src --severity-level high && make check`.
- Manual smoke (running dashboard) — see success criteria.
- Open PR `feat(agent): journey planning + arrivals tools (TM-30)`, body `Closes TM-30`, link the plan path. English title + body.

---

## Success criteria

**Automated (all exit 0):**
- `uv run task lint` (ruff check + ruff format --check + mypy strict).
- `uv run task test` including the new TfL-client, resolver, and agent-tool tests.
- `uv run bandit -r src --severity-level high` — no HIGH findings.
- `pnpm --dir web lint && pnpm --dir web test`.
- `make check` end-to-end.

**Manual (running dashboard + agent with TfL key + LLM creds):**
- Chat "plan a journey from Oxford Circus to Bank" → agent narrates legs (modes, durations, walking time).
- Chat "next arrivals at Bank" → next vehicles per platform with time-to-station.
- Chat "what's the status of Central and plan a route around it" → chains a status tool → `plan_journey_tool`.
- Click each of the three quick-prompt chips → textarea pre-fills with the chip value; Send works.

---

## What we're NOT doing

- **Rich shadcn `<JourneyCard>` rendering / a new `journey` SSE frame.** Deferred to a follow-up WP — needs new streaming-frame plumbing + parser + chat-panel interception. TM-30 narrates journeys as text.
- **Pydantic AI extraction** on station names (TfL Search + `args_schema` suffice).
- **Dedicated journey/arrivals UI panes** — chat-only per the master-plan decision.
- **`dim_stations` forward DB fast-path** — TfL Search + process cache covers it; avoids the pgbouncer cast concern.
- **New public REST endpoints** (`/journey`, `/arrivals`) — these are agent-internal tools, no OpenAPI surface change.
- **Persisting / long-term caching journey results** — process cache for name resolution only.
- **TfL HTTP 300 disambiguation flows** — we resolve to NaPTAN ourselves and pass ids to JourneyResults; ambiguity is resolved by picking the top Search match.

---

## Risks / watch-items

- **Nested TfL shapes:** journey `mode`/`instruction` are nested objects — model them as sub-models, don't expect flat aliasing.
- **`make_tools` signature change** ripples to `compile_agent` + lifespan + every existing `make_tools(...)` call site and test — update all (`grep -rn "make_tools\|compile_agent" src tests`).
- **mypy strict:** new public methods/tools need full type hints + Google-style docstrings (WHAT only).
- **Orphan tools (napkin #9):** verify both tools are registered AND that `tfl_client` actually reaches `make_tools` in the live lifespan path, not just tests.
- **TfL Search relevance:** "Bank" etc. may return a non-rail top match; acceptable for v1 (note as a known limitation), revisit if manual smoke shows bad picks.
