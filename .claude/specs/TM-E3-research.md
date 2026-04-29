# TM-E3 — Research (Phase 1)

Read-only investigation for **TM-E3: Ask tfl-monitor chat view with SSE streaming** — track `E-frontend`, phase 6 in `PROGRESS.md`. Output of this phase is a map of existing facts with no design decisions or code. Structure mirrors `TM-D5-research.md` and `TM-E1a-research.md`.

## 1. Charter and scope

### What TM-E3 owns

`PROGRESS.md` row:

> TM-E3 — *Chat view with SSE* — track `E-frontend`, phase 6, depends on TM-D5 (shipped 2026-04-29). The frontend must consume two backend routes that already exist: `POST /api/v1/chat/stream` and `GET /api/v1/chat/{thread_id}/history`.

The `app/ask/page.tsx` stub currently renders a placeholder Card with the text "Coming in TM-E3."

Track is `E-frontend`. Allowed directories: `web/`. Backend, `contracts/`, `dbt/`, `src/`, `airflow/` are out of scope.

### ADR scan

ADR 002 (contracts-first): `contracts/openapi.yaml` and `web/lib/types.ts` (auto-generated from it) are already in sync for the two chat routes. The frontend must not edit the contract. Type aliases derived from `components["schemas"]["ChatRequest"]` and `components["schemas"]["ChatMessage"]` are already present in `web/lib/types.ts`.

---

## 2. Backend contract for the two chat routes

### 2.1 OpenAPI — `POST /api/v1/chat/stream`

From `contracts/openapi.yaml` lines 291–315:

```yaml
requestBody:
  required: true
  content:
    application/json:
      schema:
        $ref: "#/components/schemas/ChatRequest"

ChatRequest:
  required: [thread_id, message]
  properties:
    thread_id: { type: string }
    message:   { type: string, minLength: 1, maxLength: 4000 }
```

Response `200 text/event-stream`:

```
SSE frames. Each `data:` frame contains a JSON payload with at least
{"type": "token" | "tool" | "end", "content": <str>}.
```

Other declared status codes: `400` (invalid body → FastAPI default 422 in practice), `500` (RFC 7807).

No `503` is declared in the OpenAPI YAML, but the implementation returns one when `pool is None` or `agent is None` (see §2.3).

### 2.2 OpenAPI — `GET /api/v1/chat/{thread_id}/history`

Path parameter: `thread_id: string`.

Response `200 application/json`:

```yaml
ChatMessage:
  required: [role, content, created_at]
  properties:
    role:       enum [user, assistant, system]
    content:    string
    created_at: string, format=date-time
```

Array of `ChatMessage`, ordered `created_at ASC, id ASC` (from `HISTORY_SQL` in `src/api/agent/history.py`).

Status codes: `200`, `404` (no rows for thread), `500` (RFC 7807).

### 2.3 Actual implementation — SSE frames emitted

Source: `src/api/main.py` (lines 236–287) and `src/api/agent/streaming.py`.

**Frame types** (from `streaming.py`):

| Frame | JSON shape | Trigger |
|---|---|---|
| `token` | `{"type": "token", "content": "<text delta>"}` | Each `messages` mode chunk from `agent.astream` that has non-empty text content |
| `tool` | `{"type": "tool", "content": "<tool_name>"}` | Each `updates` mode chunk where key `"tools"` is present; one frame per ToolMessage in `messages` list |
| `end` (success) | `{"type": "end", "content": ""}` | After `astream` exhausts normally |
| `end` (error) | `{"type": "end", "content": "error"}` | On any `Exception` in the generator (not `CancelledError`) |

**Terminal frame**: always `{"type": "end", ...}`. The connection is then closed by `EventSourceResponse`. End-of-stream is signalled by this explicit frame, not by connection close alone — but connection close also terminates the stream.

**Disconnection handling**: the generator polls `await request.is_disconnected()` before yielding each frame. On disconnect, it `return`s (no `end` frame is emitted).

**503 conditions**: if `pool is None`, returns RFC 7807 503 before even creating the SSE generator. If `agent is None` (any of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `PINECONE_API_KEY` is missing at lifespan), returns RFC 7807 503.

**Thread-id semantics**: `thread_id` is **client-supplied** in the POST body. The contract (`ChatRequest.thread_id: string`) has `min_length=1` (from `src/api/schemas.py` line 128) but no format constraint — any non-empty string is accepted. There is no `POST /chat/threads` endpoint. The frontend is responsible for generating the thread ID.

**Persistence**: user turn persisted via `append_message(pool, thread_id, role="user", content=body.message)` **before** the first frame. Assistant turn persisted **after** the stream ends cleanly (`completed=True`) by concatenating all `token` frame contents. Truncated (disconnect/error) turns are NOT persisted. The `analytics.chat_messages` table columns are `(id BIGSERIAL, thread_id TEXT, role TEXT, content TEXT, created_at TIMESTAMPTZ DEFAULT now())`.

**`ping` interval**: `EventSourceResponse(event_stream(), ping=15)` — 15 seconds. Fits Railway; Vercel Hobby closes idle connections at ~10s (flagged in TM-D5 research for TM-A5 follow-up).

### 2.4 History endpoint implementation

Source: `src/api/agent/history.py`.

```sql
SELECT role, content, created_at
FROM analytics.chat_messages
WHERE thread_id = %(thread_id)s
ORDER BY created_at ASC, id ASC
```

Returns `list[ChatMessageResponse]` (Pydantic model with `role`, `content`, `created_at: datetime`). Caller maps empty list → 404 RFC 7807. No `limit` parameter — the endpoint returns all rows for the thread (no pagination in the OpenAPI spec).

### 2.5 Env var gates

| Env var | Effect when missing |
|---|---|
| `ANTHROPIC_API_KEY` | `compile_agent` returns `None` → `/chat/stream` 503; `/history` unaffected |
| `OPENAI_API_KEY` | same |
| `PINECONE_API_KEY` | same |
| `DATABASE_URL` | pool not opened → both routes 503 |
| `LANGSMITH_*` | no LLM tracing; routes still work |
| `LOGFIRE_TOKEN` | no app tracing; routes still work |

---

## 3. Existing frontend conventions to mirror

### 3.1 `apiFetch` and `ApiError` (from `web/lib/api-client.ts`)

```ts
const DEFAULT_API_URL = "http://localhost:8000";
function baseUrl(): string {
    return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;
}

export class ApiError extends Error {
    constructor(public readonly status: number, public readonly detail: string) { ... }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${baseUrl()}${path}`, {
        ...init,
        headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
    if (!response.ok) {
        // parses RFC 7807 detail/title; falls back to statusText
        throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
}
```

Key conventions:
- `NEXT_PUBLIC_API_URL` env var, falls back to `http://localhost:8000`.
- Always sets `Accept: application/json`.
- Throws `ApiError` on non-2xx; callers catch and render fallback Alerts.
- `cache: "no-store"` is passed by each route module as part of `init` (not hardcoded in `apiFetch` itself).
- No schema validation beyond TypeScript cast — no Zod/runtime schema check.

**Critical observation for SSE**: `apiFetch` calls `response.json()` — it is designed for JSON endpoints only. An SSE stream requires a raw `fetch` call with `response.body` (a `ReadableStream`), not `apiFetch`. The chat fetcher module cannot reuse `apiFetch` for the stream itself. It may reuse `baseUrl()` (or the same `NEXT_PUBLIC_API_URL` pattern).

### 3.2 Existing fetcher modules (TM-E1b, TM-E2)

`web/lib/api/status-live.ts`:
```ts
export async function getStatusLive(): Promise<LineStatus[]> {
    return apiFetch<LineStatus[]>("/api/v1/status/live", { cache: "no-store" });
}
```

`web/lib/api/disruptions-recent.ts`:
```ts
export async function getRecentDisruptions(): Promise<Disruption[]> {
    return apiFetch<Disruption[]>("/api/v1/disruptions/recent", { cache: "no-store" });
}
```

Both modules:
- Re-export the type from `web/lib/types.ts` via `components["schemas"]["..."]`.
- Are pure async functions, no side effects.
- File-level JSDoc explaining what the function does and citing the `contracts/openapi.yaml` schema.

### 3.3 Page conventions (server component vs. client component)

`app/page.tsx` (Network Now) and `app/disruptions/page.tsx` (Disruption Log) are **async server components**: they `await` the fetcher at render time, catch `ApiError`, and render fallback `Alert` components.

The chat view is fundamentally different: it requires:
1. A text input and submit button that the user interacts with in the browser.
2. An SSE connection that must be maintained across the lifetime of the page — a streaming read loop (`ReadableStream` or `EventSource`).
3. Incremental state updates as `token` frames arrive.

Server components cannot hold state or maintain streaming connections. The Ask page **requires a `"use client"` component** (or at minimum a client component for the chat interaction panel). This is not a design decision — it is a mechanical constraint: `useState`, `useRef`, event handlers, and `EventSource`/`ReadableStream` are browser APIs that cannot run in server-side RSC.

TM-E1b and TM-E2 pattern (async server component → `await` → render) does not transfer to the chat view.

### 3.4 shadcn components installed under `web/components/ui/`

Six primitives are present:

| File | Exports |
|---|---|
| `alert.tsx` | `Alert`, `AlertAction`, `AlertDescription`, `AlertTitle` |
| `badge.tsx` | `Badge`, `badgeVariants` |
| `button.tsx` | `Button`, `buttonVariants` |
| `card.tsx` | `Card`, `CardAction`, `CardContent`, `CardDescription`, `CardFooter`, `CardHeader`, `CardTitle` |
| `skeleton.tsx` | `Skeleton` |
| `tabs.tsx` | `Tabs`, `TabsContent`, `TabsList`, `TabsTrigger`, `tabsListVariants` |

One bespoke component:
- `web/components/status-badge.tsx` — `StatusBadge` mapping severity integer to amber/green/red `Badge`.

No `textarea`, `input`, or `scroll-area` shadcn primitives are currently installed. A chat UI typically needs at minimum an `<input>`/`<textarea>` and a scrollable message list. These would need to be installed from shadcn or implemented as plain Tailwind HTML elements.

The `Skeleton` component already exists and can be used to show a loading state while the SSE stream is in progress.

### 3.5 Tailwind / Biome / Vitest config

**Biome** (`web/biome.json`): tabs, double quotes, Biome recommended rules, `lib/types.ts` excluded from linting, `vcs.useIgnoreFile=true`. No ESLint. The `assist.source.organizeImports` is on.

**Vitest** (`web/vitest.config.ts`): `jsdom` environment, globals enabled, `vitest.setup.ts` runs `@testing-library/jest-dom/vitest`. Path alias `@` → `.` (project root, not `src/`). Test pattern: `**/*.{test,spec}.{ts,tsx}`, excludes `node_modules` and `.next`.

**Dependencies already installed** (from `web/package.json`):
- `vitest@^4.1.5`, `@vitejs/plugin-react@^6.0.1`, `@testing-library/react@^16.3.2`, `@testing-library/jest-dom@^6.9.1`, `@testing-library/dom@^10.4.1`, `jsdom@^29.1.0`.
- No `@testing-library/user-event` (not installed — interactive tests would need it or `vi.stubGlobal("fetch", ...)` pattern).

No `EventSource` or `ReadableStream` mocking helpers exist in the codebase. There are no SSE test utilities anywhere under `web/`.

**TypeScript** (`web/tsconfig.json`): strict mode, `"types": ["vitest/globals", "@testing-library/jest-dom"]`, `moduleResolution: "bundler"`, path alias `@/*` → `./*`.

### 3.6 Existing test patterns

Two patterns are established:

**Fetcher unit tests** (`web/lib/api/status-live.test.ts`, `web/lib/api/disruptions-recent.test.ts`):
- `vi.stubGlobal("fetch", vi.fn())` / `vi.unstubAllGlobals()` in `beforeEach`/`afterEach`.
- `jsonResponse(body, status)` helper builds `new Response(JSON.stringify(body), ...)`.
- Asserts URL shape, headers, `cache: "no-store"`, return value, empty array, `ApiError`, network error.

**Page component tests** (`web/app/__tests__/network-now.test.tsx`, `web/app/__tests__/disruption-log.test.tsx`):
- `vi.mock("@/lib/api/...")` with `vi.importActual` to preserve non-mocked exports.
- Module-level `await import(...)` to get the mocked function reference.
- Async server component called as a function (`const ui = await NetworkNowPage(); render(ui);`).
- Asserts DOM via `screen.getByRole`, `screen.getByText`, `screen.getByLabelText`, `data-testid`, `data-tone`.

**What does NOT exist**:
- No `EventSource` mock or `ReadableStream` mock.
- No `@testing-library/user-event`.
- No MSW (Mock Service Worker).
- No existing test for any client component (`"use client"`) — all current tests are for server components or pure TS functions.

Testing a client component that consumes SSE will require a different approach: mocking the native `EventSource` constructor or the `fetch`+`ReadableStream` pipeline, and using `userEvent` or `fireEvent` to simulate typing and submit.

### 3.7 App routing structure

```
web/app/
├── __tests__/
│   ├── network-now.test.tsx      # TM-E1b
│   └── disruption-log.test.tsx   # TM-E2
├── disruptions/
│   └── page.tsx                  # TM-E2 (async server component)
├── ask/
│   └── page.tsx                  # TM-E3 stub ("Coming in TM-E3")
├── reliability/
│   └── page.tsx                  # placeholder (not yet wired)
├── globals.css
├── layout.tsx
└── page.tsx                      # TM-E1b (async server component)
```

`app/ask/page.tsx` exists and is a synchronous server component with a stub Card. TM-E3 replaces its contents.

There is **no nav component** (`web/components/nav.tsx` does not exist). `app/layout.tsx` does not include any shared navigation bar — just a root `<html>` / `<body>` wrapper with Geist fonts. The existing pages are standalone; there is no link from any page to `/ask`.

### 3.8 Security headers (from `web/next.config.ts`)

```ts
const securityHeaders = [
    { key: "X-Frame-Options",           value: "DENY" },
    { key: "X-Content-Type-Options",    value: "nosniff" },
    { key: "Referrer-Policy",           value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy",        value: "camera=(), microphone=(), geolocation=()" },
];
```

Applied via `headers()` to `source: "/(.*)"` — all routes including `/ask`. TM-E3 does not need to touch `next.config.ts`.

### 3.9 Frontend observability (Logfire / LangSmith)

Neither Logfire nor LangSmith SDK is installed in `web/`. No `@logfire/...` or `langsmith` package appears in `web/package.json`. The frontend does not touch these observability tools. The backend SSE handler is already instrumented.

---

## 4. Project conventions that constrain TM-E3

### Language / English rule

CLAUDE.md: source code, identifiers, file names, tests, docstrings — English only. Chat responses to author — PT-BR. All git artifacts (commits, PR, branch) — English.

### Tech-stack lock

Next.js 16, shadcn/ui Nova preset (`style: "radix-nova"`, `baseColor: "neutral"`), Biome (no ESLint/Prettier), Vitest (no Jest), TypeScript strict.

No new tools may be introduced without an ADR. In particular: no `@microsoft/fetch-event-source`, no Zustand, no SWR — unless there is a concrete blocker with the native `EventSource` or `fetch`+`ReadableStream` approach.

### Pre-push gate

`make check` runs:
1. `uv run task lint` (Python)
2. `uv run task test` (Python)
3. `uv run task dbt-parse`
4. `pnpm --dir web lint` (Biome)
5. `pnpm --dir web test` (Vitest)
6. `pnpm --dir web build` (Next.js)

TM-E3 must pass all six steps.

### No Markdown in `.claude/` chat

File content of the research/plan/spec files is English. Chat replies to the author in PT-BR. No contradiction for TM-E3 work.

---

## 5. Open questions for Phase 2

1. **Thread-id generation**: the backend accepts any non-empty client-supplied string. Should the frontend generate a UUID v4 on page load (e.g., `crypto.randomUUID()`) and hold it in `useState` for the session lifetime, or should it persist across page refreshes (e.g., `localStorage` or `sessionStorage`)? If the page is stateless, a new UUID per mount means history is inaccessible after reload.

2. **History on mount**: should the chat view call `GET /history` on mount to pre-populate the message list for a returning thread, or is the page stateless (always starts empty)? If the thread ID is per-session (not persisted), there is nothing to restore on reload and the history endpoint is only useful for other consumers.

3. **Navigation link**: there is no shared nav component and no link to `/ask` from any page. Where should the chat link live — as a new shared `nav.tsx` component added to `layout.tsx`, or as a standalone link on the landing page, or not linked at all for TM-E3?

4. **`EventSource` vs `fetch`+`ReadableStream`**: `EventSource` is simpler (browser reconnects automatically, parses SSE framing) but does not support `POST` requests — it only issues `GET`. The backend requires `POST /api/v1/chat/stream`. The correct approach for a `POST` SSE is `fetch(url, { method: "POST", body: ... })` followed by streaming `response.body`. Plan phase must confirm this and decide whether any polyfill or library (e.g., `@microsoft/fetch-event-source`) is warranted or whether raw `fetch`+`ReadableStream` is sufficient.

5. **SSE parsing in the browser**: the `ReadableStream` returned by `fetch` delivers raw bytes, not parsed SSE frames. The frontend must parse the `data: ...\n\n` framing. Is a custom SSE parser needed, or is the existing server output simple enough that a line-split approach is safe?

6. **Streaming UX while the agent is thinking**: the backend may take several seconds before emitting the first `token` frame (model latency + potential tool calls that emit `tool` frames first). What is the desired UX during that window — a `Skeleton` loader, a spinner, the `tool` frames rendered as "Looking up…" labels, or nothing?

7. **Error UX for 503 (agent not compiled)**: the agent returns a JSON 503 (RFC 7807) as an HTTP-level non-2xx response **before** the SSE stream starts. How should the UI distinguish "agent is down" (503 on the POST itself) from a mid-stream `{"type":"end","content":"error"}` frame?

8. **Message persistence across refresh**: if `thread_id` is held in `useState` only, the history is lost on reload. If persisted to `localStorage`, the user can resume. The history endpoint supports this — plan phase must decide.

9. **Markdown rendering**: the assistant's answer may contain markdown (citations like "Source: TfL Annual Report p.42"). Should the frontend render markdown (e.g., a lightweight `marked` or `react-markdown` dependency) or display plain text? No markdown renderer is currently installed in `web/`.

10. **Input: `<textarea>` vs `<input>`**: the backend accepts messages up to 4000 chars. Should the input box grow with content (textarea) or stay fixed (input)? Neither a shadcn `textarea` nor a shadcn `input` primitive is currently installed.

11. **`tool` frame UX**: when `{"type":"tool","content":"query_tube_status"}` arrives, the backend is mid-tool-call. How should the UI surface this — as an ephemeral "Using tool: query_tube_status…" status line, or silently ignored?

12. **Test strategy for the client component**: all current tests cover server components or pure fetcher functions. Testing an SSE client component requires mocking `fetch` with a streaming `ReadableStream` body. Is the plan to write full component tests with RTL + mock streams, or to test the stream-parsing logic in isolation (pure unit test) and leave the component integration to a simpler smoke test?

---

## 6. Files inventoried

| File | Content |
|---|---|
| `contracts/openapi.yaml` | Full OpenAPI 3.1 spec; chat route schemas quoted in §2.1–2.2 |
| `src/api/main.py` | FastAPI app; `post_chat_stream` and `get_chat_history` handlers (lines 236–305) |
| `src/api/agent/streaming.py` | `project`, `frame_token`, `frame_tool`, `frame_end`, `serialise`, `_extract_text` — SSE frame projection |
| `src/api/agent/history.py` | `append_message`, `fetch_history`; `INSERT_SQL`, `HISTORY_SQL` |
| `src/api/agent/graph.py` | `compile_agent`; env var guards; `InMemorySaver`; `create_react_agent` |
| `src/api/agent/prompts.py` | `SYSTEM_PROMPT_TEMPLATE`; `render()` |
| `src/api/agent/tools.py` | Five tool definitions (first 40 lines read) |
| `src/api/schemas.py` | `ChatRequest`, `ChatMessageResponse`, `Problem` Pydantic models |
| `web/lib/api-client.ts` | `apiFetch`, `ApiError`, `baseUrl()` |
| `web/lib/api/status-live.ts` | TM-E1b fetcher — canonical fetcher pattern |
| `web/lib/api/disruptions-recent.ts` | TM-E2 fetcher — second canonical fetcher |
| `web/lib/api/status-live.test.ts` | Fetcher unit test — `vi.stubGlobal("fetch")` pattern |
| `web/lib/api/disruptions-recent.test.ts` | Second fetcher unit test |
| `web/lib/types.ts` | Auto-generated OpenAPI → TS; `ChatRequest` and `ChatMessage` schemas confirmed present |
| `web/lib/utils.ts` | `cn(...)` Tailwind merge helper |
| `web/app/page.tsx` | Network Now — async server component pattern |
| `web/app/disruptions/page.tsx` | Disruption Log — async server component pattern |
| `web/app/ask/page.tsx` | TM-E3 stub — placeholder Card |
| `web/app/reliability/page.tsx` | Reliability placeholder (not wired) |
| `web/app/layout.tsx` | Root layout — no nav component present |
| `web/app/__tests__/network-now.test.tsx` | Page component test — `vi.mock` + `await Page()` + render pattern |
| `web/app/__tests__/disruption-log.test.tsx` | Second page component test |
| `web/components/ui/alert.tsx` | `Alert`, `AlertTitle`, `AlertDescription`, `AlertAction` |
| `web/components/ui/badge.tsx` | `Badge`, `badgeVariants` |
| `web/components/ui/button.tsx` | `Button`, `buttonVariants` |
| `web/components/ui/card.tsx` | `Card`, `CardHeader`, `CardTitle`, `CardContent`, `CardFooter`, etc. |
| `web/components/ui/skeleton.tsx` | `Skeleton` |
| `web/components/ui/tabs.tsx` | `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` |
| `web/components/status-badge.tsx` | `StatusBadge` — severity → tone badge |
| `web/components.json` | shadcn config: `style: "radix-nova"`, `baseColor: "neutral"`, `rsc: true` |
| `web/package.json` | Dependencies; confirms no `EventSource`/SSE library, no markdown renderer, no textarea/input shadcn primitives |
| `web/biome.json` | Biome config: tabs, double quotes, recommended rules |
| `web/vitest.config.ts` | Vitest: jsdom, globals, `@` alias, setupFiles |
| `web/vitest.setup.ts` | Registers `@testing-library/jest-dom/vitest` |
| `web/tsconfig.json` | Strict mode, `vitest/globals` types, bundler resolution |
| `web/next.config.ts` | Security headers (all four); applied to all routes |
| `Makefile` | `make check` chains lint+test+dbt-parse+pnpm lint+pnpm test+pnpm build |
| `PROGRESS.md` | TM-E3 row: phase 6, track E-frontend, status pending |
| `.claude/adrs/002-contracts-first.md` | ADR 002 — any contract change needs ADR + cross-track broadcast |
| `.claude/specs/TM-D5-research.md` | Backend context: SSE frame design, history persistence, agent topology |
| `.claude/specs/TM-E1a-research.md` | Frontend scaffold research — Vitest setup, shadcn, server component pattern |

---

## 7. What we are NOT exploring in this phase

- No code is written or modified.
- No design decisions for the chat component layout, message bubble styling, or input affordances.
- No evaluation of third-party SSE libraries (e.g., `@microsoft/fetch-event-source`).
- No assessment of whether markdown rendering (e.g., `react-markdown`) is the right choice — that is a plan-phase decision.
- No exploration of the backend beyond what is needed to understand the SSE contract and history shape.
- No exploration of `web/app/reliability/page.tsx` beyond confirming it is a placeholder.
- No exploration of `src/api/agent/rag.py`, `src/api/agent/extraction.py` — these are internal to the backend.
