# 011 — Structured `journey` / `arrivals` SSE frames for chat cards

Status: accepted
Date: 2026-05-27

## Context

TM-30 (ADR 009) shipped `plan_journey_tool` and `get_arrivals_tool`. Both
build a structured dict — a journey's per-leg breakdown, a station's
arrivals grouped by platform — which LangChain then JSON-encodes into the
`ToolMessage` content and hands to the LLM. Only the LLM's **prose** reply
reached the frontend over SSE: the stream carried `token` / `tool` / `end`
frames, all string-valued. ADR 009 explicitly deferred the rich
`<JourneyCard>` ("which would add a structured SSE frame to the public
surface") to a follow-up WP.

Two problems surfaced in the chat panel (this WP):

- The assistant's Markdown narration rendered as literal text, so
  `**Metropolitan line**` showed the asterisks.
- A journey/arrivals answer is inherently tabular (legs, platforms,
  countdowns) and reads poorly as a paragraph.

The structured data already exists at the tool layer; it was simply
discarded before reaching the browser.

## Decision

Surface the structured tool result as a new SSE frame type, keeping the
uniform `{"type": <str>, "content": <str>}` envelope (content is the view
JSON-encoded, decoded client-side):

- `src/api/agent/streaming.py`: in the `updates`/`tools` projection, after
  the existing `tool` frame, attempt `json.loads(ToolMessage.content)` for
  the two card tools and emit a `journey` (`plan_journey_tool`) or
  `arrivals` (`get_arrivals_tool`) frame. A tool's plain error-string
  return is not valid JSON-object, so it yields no card frame and the
  answer stays prose-only. No change to `tools.py`.
- `contracts/openapi.yaml`: document the `journey` / `arrivals` frame
  types and add `JourneyView`, `JourneyLeg`, `ArrivalsView`,
  `ArrivalsPlatform`, `ArrivalPrediction` to `components.schemas`,
  mirroring the dict shapes the tools already build. `web/lib/types.ts` is
  regenerated so the frontend cards consume generated types.

The cards are rendered with the existing hand-rolled `tfl-*` design-system
CSS, not shadcn/Tailwind, to stay consistent with the rest of the app and
avoid introducing a second styling system (CLAUDE.md "lean by default").

## Consequences

- **Contract change → this ADR + `contract:` PR.** The addition is purely
  additive: the SSE envelope is unchanged, the new schemas are new
  components, and no tier-1/tier-2 Kafka, SQL, or dbt source is touched, so
  the CI source-mirror diff gate is unaffected.
- The view schemas are hand-authored in OpenAPI rather than derived from
  Pydantic models; the backend keeps emitting plain dicts. A backend test
  asserts the emitted frame shape, which is the guard against drift.
- Card frames are never persisted to `analytics.chat_messages` — only
  `token` text is buffered for the assistant turn — so chat history stays
  a faithful text transcript.
- Journey legs expose `mode` + a free-text `summary` (no line id), so the
  card colours legs by mode and shows the summary verbatim; the arrivals
  board has line names and colours them via the existing line palette.
