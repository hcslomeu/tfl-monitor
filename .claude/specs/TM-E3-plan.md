# TM-E3 — Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `app/ask/page.tsx` stub with a working chat view that streams answers from `POST /api/v1/chat/stream` and displays user/agent turns in the browser.

**Architecture:** A `"use client"` `ChatView` component renders the message list, a textarea, and a Send button. On submit it calls a generator `streamChat()` that issues `fetch(POST)`, parses the SSE stream off `response.body`, and yields `{type, content}` frames. A small `SSEParser` accumulates byte chunks, splits on the SSE event boundary (`\n\n`), strips comment lines (`:`-prefixed pings), and JSON-parses each `data:` line. The page runs on a per-mount `crypto.randomUUID()` thread id (no persistence, no history fetch). Tool frames render as an ephemeral status line; HTTP-level errors (e.g. 503) surface as a top-of-card `Alert`; mid-stream `end:error` marks the in-flight assistant bubble as errored.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript strict, Tailwind, shadcn/ui (Card, Alert, Button, Skeleton — already installed), Biome, Vitest + React Testing Library, native `fetch` + `ReadableStream` + `TextDecoder` (no new dependencies).

---

## Resolved decisions (carried from research §5)

| # | Question | Decision |
|---|---|---|
| 1 | Thread-id generation | `crypto.randomUUID()` once per mount, kept in `useRef`. No persistence. |
| 2 | History on mount | Skip. Thread is per-session; nothing to restore. |
| 3 | Navigation link | Add a small "Ask the agent →" link on the Network Now landing (`app/page.tsx`). No shared nav component. |
| 4 | EventSource vs fetch | `fetch` + `ReadableStream`. `EventSource` only supports GET. |
| 5 | SSE parsing | Custom ~40-line parser. Backend frames are simple `data: {...}\n\n`. |
| 6 | Streaming UX | Inline `Skeleton` inside the empty assistant bubble until the first `token`. Tool frames render as an ephemeral status line above the bubble. |
| 7 | 503 vs mid-stream error | HTTP non-2xx → top-of-card `Alert`; mid-stream `end:error` → mark the current assistant bubble `data-errored="true"`. |
| 8 | Persistence across refresh | Skip. State only. |
| 9 | Markdown rendering | Plain text + `whitespace-pre-wrap`. No new dependency. |
| 10 | Input element | Plain HTML `<textarea>`, `rows={3}`, `maxLength={4000}`. |
| 11 | Tool frame UX | Ephemeral status line ("Using tool: <name>…"); cleared when the next `token` arrives. |
| 12 | Test strategy | (a) parser unit tests; (b) `streamChat` fetcher tests with mocked `ReadableStream`; (c) `ChatView` smoke tests with `vi.stubGlobal("fetch")` driving a streaming `Response`. No `@testing-library/user-event` install — use `fireEvent`. |

---

## File structure

| Path | Status | Responsibility |
|---|---|---|
| `web/lib/sse-parser.ts` | create | Pure stateful parser: accumulate `Uint8Array` chunks, emit `Frame` objects on `\n\n` boundaries, ignore SSE comments. |
| `web/lib/sse-parser.test.ts` | create | Vitest unit tests for parser. |
| `web/lib/api/chat-stream.ts` | create | `streamChat(body, signal?)` async generator: POSTs `ChatRequest`, throws `ApiError` on non-2xx, yields `Frame` from `response.body`. |
| `web/lib/api/chat-stream.test.ts` | create | Vitest fetcher tests with mocked `Response`/`ReadableStream`. |
| `web/components/chat-view.tsx` | create | `"use client"` component: message list, textarea, Send button, status line, error alert. |
| `web/app/ask/page.tsx` | modify | Replace stub. Render `<ChatView />` inside the existing `<main>` shell pattern. |
| `web/app/page.tsx` | modify | Add a single "Ask the agent →" link in the header. |
| `web/app/__tests__/ask.test.tsx` | create | Smoke test for the chat page wiring `vi.stubGlobal("fetch")` with a streaming `Response`. |

No changes to `contracts/`, `web/lib/api-client.ts`, `web/lib/types.ts`, `web/next.config.ts`, `web/biome.json`, `web/vitest.config.ts`, or `web/package.json`.

---

## Phase 1 — SSE parser (pure logic, TDD)

### Task 1: Frame type + empty parser

**Files:**
- Create: `web/lib/sse-parser.ts`

- [ ] **Step 1: Create the file with type and stub class**

```ts
// web/lib/sse-parser.ts
/**
 * Minimal SSE parser for the `/chat/stream` event-stream.
 *
 * The backend (`src/api/agent/streaming.py`) emits one JSON payload
 * per `data:` line, terminated by a blank line. `EventSourceResponse`
 * also injects `: ping` comments every 15s — those lines are skipped.
 */

export type Frame =
	| { type: "token"; content: string }
	| { type: "tool"; content: string }
	| { type: "end"; content: string };

export class SSEParser {
	private buffer = "";
	private decoder = new TextDecoder();

	push(chunk: Uint8Array): Frame[] {
		this.buffer += this.decoder.decode(chunk, { stream: true });
		return [];
	}
}
```

- [ ] **Step 2: Commit the scaffold**

```bash
git add web/lib/sse-parser.ts
git commit -m "feat(web): add SSE parser scaffold for chat stream"
```

---

### Task 2: Parse a single complete frame

**Files:**
- Create: `web/lib/sse-parser.test.ts`
- Modify: `web/lib/sse-parser.ts`

- [ ] **Step 1: Write the failing test**

```ts
// web/lib/sse-parser.test.ts
import { describe, expect, it } from "vitest";

import { type Frame, SSEParser } from "./sse-parser";

const encoder = new TextEncoder();

function bytes(text: string): Uint8Array {
	return encoder.encode(text);
}

describe("SSEParser", () => {
	it("parses a single complete data frame", () => {
		const parser = new SSEParser();

		const frames = parser.push(
			bytes('data: {"type":"token","content":"hi"}\n\n'),
		);

		expect(frames).toEqual<Frame[]>([{ type: "token", content: "hi" }]);
	});
});
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
pnpm --dir web test sse-parser
```

Expected: 1 fail (`Expected: [{type:"token",content:"hi"}], Received: []`).

- [ ] **Step 3: Implement push()**

Replace the body of `push` in `web/lib/sse-parser.ts`:

```ts
push(chunk: Uint8Array): Frame[] {
	this.buffer += this.decoder.decode(chunk, { stream: true });

	const frames: Frame[] = [];
	let boundary = this.buffer.indexOf("\n\n");
	while (boundary !== -1) {
		const event = this.buffer.slice(0, boundary);
		this.buffer = this.buffer.slice(boundary + 2);
		const parsed = parseEvent(event);
		if (parsed) frames.push(parsed);
		boundary = this.buffer.indexOf("\n\n");
	}
	return frames;
}
```

Add the `parseEvent` helper at the bottom of the file:

```ts
function parseEvent(event: string): Frame | null {
	const dataLines: string[] = [];
	for (const rawLine of event.split("\n")) {
		const line = rawLine.replace(/\r$/, "");
		if (line === "" || line.startsWith(":")) continue;
		if (line.startsWith("data:")) {
			dataLines.push(line.slice(5).trimStart());
		}
	}
	if (dataLines.length === 0) return null;

	try {
		const payload = JSON.parse(dataLines.join("\n")) as unknown;
		if (
			typeof payload === "object" &&
			payload !== null &&
			"type" in payload &&
			"content" in payload &&
			typeof (payload as { type: unknown }).type === "string" &&
			typeof (payload as { content: unknown }).content === "string"
		) {
			const { type, content } = payload as { type: string; content: string };
			if (type === "token" || type === "tool" || type === "end") {
				return { type, content };
			}
		}
	} catch {
		// Malformed JSON — drop the frame rather than crashing the stream.
	}
	return null;
}
```

- [ ] **Step 4: Run and verify pass**

```bash
pnpm --dir web test sse-parser
```

Expected: 1 pass.

- [ ] **Step 5: Commit**

```bash
git add web/lib/sse-parser.ts web/lib/sse-parser.test.ts
git commit -m "feat(web): parse single SSE frame in SSEParser"
```

---

### Task 3: Multiple frames in one chunk

**Files:**
- Modify: `web/lib/sse-parser.test.ts`

- [ ] **Step 1: Add the failing test**

Inside the `describe("SSEParser", …)` block:

```ts
it("parses multiple frames delivered in a single chunk", () => {
	const parser = new SSEParser();

	const frames = parser.push(
		bytes(
			[
				'data: {"type":"tool","content":"query_tube_status"}\n\n',
				'data: {"type":"token","content":"The "}\n\n',
				'data: {"type":"token","content":"Piccadilly"}\n\n',
			].join(""),
		),
	);

	expect(frames).toEqual<Frame[]>([
		{ type: "tool", content: "query_tube_status" },
		{ type: "token", content: "The " },
		{ type: "token", content: "Piccadilly" },
	]);
});
```

- [ ] **Step 2: Run — should already pass with the loop in Task 2**

```bash
pnpm --dir web test sse-parser
```

Expected: 2 pass.

- [ ] **Step 3: Commit**

```bash
git add web/lib/sse-parser.test.ts
git commit -m "test(web): cover multi-frame chunk in SSEParser"
```

---

### Task 4: Partial frame across two chunks

**Files:**
- Modify: `web/lib/sse-parser.test.ts`

- [ ] **Step 1: Add the failing test**

```ts
it("buffers a partial frame and emits it after the boundary arrives", () => {
	const parser = new SSEParser();

	const first = parser.push(bytes('data: {"type":"token","cont'));
	const second = parser.push(bytes('ent":"hello"}\n\n'));

	expect(first).toEqual<Frame[]>([]);
	expect(second).toEqual<Frame[]>([{ type: "token", content: "hello" }]);
});
```

- [ ] **Step 2: Run — should pass with current logic**

```bash
pnpm --dir web test sse-parser
```

Expected: 3 pass.

- [ ] **Step 3: Commit**

```bash
git add web/lib/sse-parser.test.ts
git commit -m "test(web): cover partial-chunk buffering in SSEParser"
```

---

### Task 5: Skip ping comments and unknown frame types

**Files:**
- Modify: `web/lib/sse-parser.test.ts`

- [ ] **Step 1: Add the failing tests**

```ts
it("ignores SSE comment lines (e.g. EventSourceResponse pings)", () => {
	const parser = new SSEParser();

	const frames = parser.push(
		bytes(
			[
				": ping\n\n",
				'data: {"type":"end","content":""}\n\n',
			].join(""),
		),
	);

	expect(frames).toEqual<Frame[]>([{ type: "end", content: "" }]);
});

it("drops frames whose type is not token/tool/end", () => {
	const parser = new SSEParser();

	const frames = parser.push(
		bytes('data: {"type":"unknown","content":"x"}\n\n'),
	);

	expect(frames).toEqual<Frame[]>([]);
});

it("drops frames with malformed JSON instead of throwing", () => {
	const parser = new SSEParser();

	expect(() => parser.push(bytes("data: {not-json\n\n"))).not.toThrow();
});
```

- [ ] **Step 2: Run — all three should pass with current logic**

```bash
pnpm --dir web test sse-parser
```

Expected: 6 pass.

- [ ] **Step 3: Commit**

```bash
git add web/lib/sse-parser.test.ts
git commit -m "test(web): cover comments, unknown types, malformed JSON in SSEParser"
```

---

## Phase 2 — `streamChat` fetcher

### Task 6: Happy-path fetcher

**Files:**
- Create: `web/lib/api/chat-stream.ts`
- Create: `web/lib/api/chat-stream.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// web/lib/api/chat-stream.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import { type Frame } from "@/lib/sse-parser";
import { streamChat } from "./chat-stream";

const encoder = new TextEncoder();

function streamFrom(...chunks: string[]): ReadableStream<Uint8Array> {
	return new ReadableStream({
		start(controller) {
			for (const c of chunks) controller.enqueue(encoder.encode(c));
			controller.close();
		},
	});
}

function streamingResponse(
	body: ReadableStream<Uint8Array>,
	status = 200,
): Response {
	return new Response(body, {
		status,
		headers: { "content-type": "text/event-stream" },
	});
}

describe("streamChat", () => {
	const fetchMock = vi.fn();

	beforeEach(() => {
		fetchMock.mockReset();
		vi.stubGlobal("fetch", fetchMock);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("yields parsed frames in order from a streaming response", async () => {
		fetchMock.mockResolvedValueOnce(
			streamingResponse(
				streamFrom(
					'data: {"type":"tool","content":"query_tube_status"}\n\n',
					'data: {"type":"token","content":"Hi"}\n\n',
					'data: {"type":"end","content":""}\n\n',
				),
			),
		);

		const collected: Frame[] = [];
		for await (const frame of streamChat({
			thread_id: "t-1",
			message: "hello",
		})) {
			collected.push(frame);
		}

		expect(collected).toEqual<Frame[]>([
			{ type: "tool", content: "query_tube_status" },
			{ type: "token", content: "Hi" },
			{ type: "end", content: "" },
		]);

		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toMatch(/\/api\/v1\/chat\/stream$/);
		expect(init).toMatchObject({ method: "POST" });
		expect(init?.headers).toMatchObject({
			"Content-Type": "application/json",
			Accept: "text/event-stream",
		});
		expect(JSON.parse(init?.body as string)).toEqual({
			thread_id: "t-1",
			message: "hello",
		});
	});
});
```

- [ ] **Step 2: Run the test and watch it fail (module not found)**

```bash
pnpm --dir web test chat-stream
```

Expected: fail with "Cannot find module './chat-stream'".

- [ ] **Step 3: Implement the fetcher**

```ts
// web/lib/api/chat-stream.ts
/**
 * SSE fetcher for `POST /api/v1/chat/stream`.
 *
 * Yields `Frame` objects parsed from the response body. `EventSource`
 * only supports GET, so we use `fetch` + `ReadableStream` and a custom
 * `SSEParser`. Non-2xx responses raise `ApiError` before any frame is
 * yielded; `AbortSignal` cancels both the HTTP request and the read.
 */

import { ApiError } from "@/lib/api-client";
import { type Frame, SSEParser } from "@/lib/sse-parser";
import type { components } from "@/lib/types";

export type ChatRequest = components["schemas"]["ChatRequest"];

const DEFAULT_API_URL = "http://localhost:8000";

function baseUrl(): string {
	return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;
}

export async function* streamChat(
	body: ChatRequest,
	signal?: AbortSignal,
): AsyncGenerator<Frame, void, unknown> {
	const response = await fetch(`${baseUrl()}/api/v1/chat/stream`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Accept: "text/event-stream",
		},
		body: JSON.stringify(body),
		signal,
	});

	if (!response.ok) {
		let detail = response.statusText;
		try {
			const problem = (await response.json()) as {
				detail?: string;
				title?: string;
			};
			detail = problem.detail ?? problem.title ?? detail;
		} catch {
			// Body was not JSON; keep status text.
		}
		throw new ApiError(response.status, detail);
	}

	if (!response.body) {
		throw new ApiError(response.status, "empty response body");
	}

	const parser = new SSEParser();
	const reader = response.body.getReader();
	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			if (value) {
				for (const frame of parser.push(value)) yield frame;
			}
		}
	} finally {
		reader.releaseLock();
	}
}
```

- [ ] **Step 4: Run and verify pass**

```bash
pnpm --dir web test chat-stream
```

Expected: 1 pass.

- [ ] **Step 5: Commit**

```bash
git add web/lib/api/chat-stream.ts web/lib/api/chat-stream.test.ts
git commit -m "feat(web): add streamChat SSE fetcher for /chat/stream"
```

---

### Task 7: 503 raises ApiError

**Files:**
- Modify: `web/lib/api/chat-stream.test.ts`

- [ ] **Step 1: Add the failing test**

```ts
it("throws ApiError when the API returns a non-2xx response", async () => {
	fetchMock.mockResolvedValueOnce(
		new Response(
			JSON.stringify({ detail: "agent unavailable", title: "503 Service Unavailable" }),
			{
				status: 503,
				headers: { "content-type": "application/problem+json" },
			},
		),
	);

	const generator = streamChat({ thread_id: "t-1", message: "hi" });

	await expect(generator.next()).rejects.toBeInstanceOf(ApiError);
});

it("surfaces the RFC 7807 detail in ApiError.detail", async () => {
	fetchMock.mockResolvedValueOnce(
		new Response(JSON.stringify({ detail: "agent unavailable" }), {
			status: 503,
			headers: { "content-type": "application/problem+json" },
		}),
	);

	const generator = streamChat({ thread_id: "t-1", message: "hi" });

	await expect(generator.next()).rejects.toMatchObject({
		status: 503,
		detail: "agent unavailable",
	});
});
```

- [ ] **Step 2: Run — should pass with current logic**

```bash
pnpm --dir web test chat-stream
```

Expected: 3 pass.

- [ ] **Step 3: Commit**

```bash
git add web/lib/api/chat-stream.test.ts
git commit -m "test(web): cover 503 → ApiError in streamChat"
```

---

### Task 8: Network error propagates

**Files:**
- Modify: `web/lib/api/chat-stream.test.ts`

- [ ] **Step 1: Add the failing test**

```ts
it("propagates network failures so the caller can render a fallback", async () => {
	fetchMock.mockRejectedValueOnce(new TypeError("network down"));

	const generator = streamChat({ thread_id: "t-1", message: "hi" });

	await expect(generator.next()).rejects.toThrow(/network down/);
});

it("buffers across chunks emitted by the stream reader", async () => {
	fetchMock.mockResolvedValueOnce(
		streamingResponse(
			streamFrom(
				'data: {"type":"token","cont',
				'ent":"hello"}\n\n',
				'data: {"type":"end","content":""}\n\n',
			),
		),
	);

	const collected: Frame[] = [];
	for await (const frame of streamChat({ thread_id: "t-1", message: "hi" })) {
		collected.push(frame);
	}

	expect(collected).toEqual<Frame[]>([
		{ type: "token", content: "hello" },
		{ type: "end", content: "" },
	]);
});
```

- [ ] **Step 2: Run — should pass**

```bash
pnpm --dir web test chat-stream
```

Expected: 5 pass.

- [ ] **Step 3: Commit**

```bash
git add web/lib/api/chat-stream.test.ts
git commit -m "test(web): cover network errors and chunk buffering in streamChat"
```

---

## Phase 3 — `ChatView` client component

### Task 9: Render empty state

**Files:**
- Create: `web/components/chat-view.tsx`
- Create: `web/app/__tests__/ask.test.tsx` (will be extended in later tasks)

- [ ] **Step 1: Write the failing test**

```tsx
// web/app/__tests__/ask.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AskPage from "@/app/ask/page";

describe("Ask page (TM-E3 chat view)", () => {
	beforeEach(() => {
		vi.stubGlobal("crypto", {
			...globalThis.crypto,
			randomUUID: () => "thread-test-uuid",
		});
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it("renders the chat shell with input and disabled send button", () => {
		render(<AskPage />);

		expect(
			screen.getByRole("heading", { name: /ask tfl-monitor/i }),
		).toBeInTheDocument();
		expect(screen.getByLabelText(/message/i)).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
	});
});
```

- [ ] **Step 2: Run — test will fail, page is the stub**

```bash
pnpm --dir web test ask
```

Expected: fail (stub renders "Coming in TM-E3", no textarea, no Send button).

- [ ] **Step 3: Create the ChatView component (empty-state shell only)**

```tsx
// web/components/chat-view.tsx
"use client";

/**
 * Conversational chat view for `/ask`.
 *
 * Talks to `POST /api/v1/chat/stream` via `streamChat()` and renders
 * incremental tokens, tool-use status, and final/errored states.
 */

import { type FormEvent, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-client";
import { streamChat } from "@/lib/api/chat-stream";

type Role = "user" | "assistant";

interface Message {
	role: Role;
	content: string;
	errored?: boolean;
}

export function ChatView() {
	const threadIdRef = useRef<string>(crypto.randomUUID());
	const [messages, setMessages] = useState<Message[]>([]);
	const [input, setInput] = useState("");
	const [busy, setBusy] = useState(false);
	const [agentStatus, setAgentStatus] = useState<string | null>(null);
	const [serviceError, setServiceError] = useState<string | null>(null);

	async function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		const trimmed = input.trim();
		if (!trimmed || busy) return;
		setInput("");
		setBusy(true);
		setServiceError(null);
		setAgentStatus(null);
		setMessages((prev) => [
			...prev,
			{ role: "user", content: trimmed },
			{ role: "assistant", content: "" },
		]);

		try {
			let assistantContent = "";
			let endedWithError = false;
			for await (const frame of streamChat({
				thread_id: threadIdRef.current,
				message: trimmed,
			})) {
				if (frame.type === "token") {
					assistantContent += frame.content;
					setAgentStatus(null);
					setMessages((prev) => {
						const next = [...prev];
						next[next.length - 1] = {
							role: "assistant",
							content: assistantContent,
						};
						return next;
					});
				} else if (frame.type === "tool") {
					setAgentStatus(`Using tool: ${frame.content}…`);
				} else if (frame.type === "end") {
					endedWithError = frame.content === "error";
				}
			}
			if (endedWithError) {
				setMessages((prev) => {
					const next = [...prev];
					next[next.length - 1] = {
						role: "assistant",
						content: assistantContent || "Stream interrupted.",
						errored: true,
					};
					return next;
				});
			}
		} catch (err) {
			setMessages((prev) => prev.slice(0, -2));
			if (err instanceof ApiError) {
				setServiceError(err.detail || `HTTP ${err.status}`);
			} else if (err instanceof Error && err.message) {
				setServiceError(err.message);
			} else {
				setServiceError("Unknown error");
			}
		} finally {
			setBusy(false);
			setAgentStatus(null);
		}
	}

	return (
		<Card className="w-full">
			<CardHeader>
				<CardTitle>Ask tfl-monitor</CardTitle>
				<CardDescription>
					Conversational agent over live TfL operations and strategy
					documents. Answers stream as the agent thinks.
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				{serviceError ? (
					<Alert role="alert" data-tone="destructive">
						<AlertTitle>Agent unavailable</AlertTitle>
						<AlertDescription>{serviceError}</AlertDescription>
					</Alert>
				) : null}

				{messages.length > 0 ? (
					<ul
						aria-label="Conversation"
						className="flex flex-col gap-3"
						data-testid="conversation"
					>
						{messages.map((message, index) => {
							const isLast = index === messages.length - 1;
							const showSkeleton =
								busy && isLast && message.role === "assistant" &&
								message.content === "";
							return (
								<li
									key={index}
									data-role={message.role}
									data-errored={message.errored ? "true" : undefined}
									className="flex flex-col gap-1"
								>
									<span className="text-xs font-medium uppercase text-muted-foreground">
										{message.role === "user" ? "You" : "Agent"}
									</span>
									{showSkeleton ? (
										<Skeleton className="h-4 w-32" />
									) : (
										<p className="whitespace-pre-wrap text-sm">
											{message.content}
										</p>
									)}
								</li>
							);
						})}
					</ul>
				) : null}

				{agentStatus ? (
					<p
						data-testid="agent-status"
						className="text-sm text-muted-foreground"
					>
						{agentStatus}
					</p>
				) : null}

				<form onSubmit={handleSubmit} className="flex flex-col gap-2">
					<label htmlFor="chat-input" className="sr-only">
						Message
					</label>
					<textarea
						id="chat-input"
						rows={3}
						maxLength={4000}
						value={input}
						onChange={(e) => setInput(e.target.value)}
						disabled={busy}
						placeholder="Ask about tube status, disruptions, or strategy…"
						className="w-full rounded-md border bg-transparent p-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
					/>
					<div className="flex justify-end">
						<Button type="submit" disabled={busy || !input.trim()}>
							{busy ? "Streaming…" : "Send"}
						</Button>
					</div>
				</form>
			</CardContent>
		</Card>
	);
}
```

- [ ] **Step 4: Replace the Ask page stub**

Overwrite `web/app/ask/page.tsx`:

```tsx
import { ChatView } from "@/components/chat-view";

export default function AskPage() {
	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-12">
			<ChatView />
		</main>
	);
}
```

- [ ] **Step 5: Run and verify the empty-state test passes**

```bash
pnpm --dir web test ask
```

Expected: 1 pass.

- [ ] **Step 6: Commit**

```bash
git add web/components/chat-view.tsx web/app/ask/page.tsx web/app/__tests__/ask.test.tsx
git commit -m "feat(web): wire ChatView client component into /ask"
```

---

### Task 10: Streaming smoke test

**Files:**
- Modify: `web/app/__tests__/ask.test.tsx`

- [ ] **Step 1: Add the test helpers and the streaming case**

Inside the same `describe` block in `web/app/__tests__/ask.test.tsx`:

```tsx
const encoder = new TextEncoder();

function streamFrom(...chunks: string[]): ReadableStream<Uint8Array> {
	return new ReadableStream({
		start(controller) {
			for (const c of chunks) controller.enqueue(encoder.encode(c));
			controller.close();
		},
	});
}

function streamingResponse(body: ReadableStream<Uint8Array>): Response {
	return new Response(body, {
		status: 200,
		headers: { "content-type": "text/event-stream" },
	});
}

it("streams tokens into the assistant bubble after submit", async () => {
	const fetchMock = vi.fn().mockResolvedValueOnce(
		streamingResponse(
			streamFrom(
				'data: {"type":"token","content":"Hello "}\n\n',
				'data: {"type":"token","content":"world"}\n\n',
				'data: {"type":"end","content":""}\n\n',
			),
		),
	);
	vi.stubGlobal("fetch", fetchMock);

	render(<AskPage />);

	fireEvent.change(screen.getByLabelText(/message/i), {
		target: { value: "hi there" },
	});
	fireEvent.submit(screen.getByLabelText(/message/i).closest("form")!);

	const assistantBubble = await screen.findByText(/hello world/i);
	expect(assistantBubble).toBeInTheDocument();

	const conversation = screen.getByTestId("conversation");
	expect(conversation).toHaveTextContent("hi there");

	expect(fetchMock).toHaveBeenCalledTimes(1);
	const [, init] = fetchMock.mock.calls[0];
	expect(JSON.parse(init?.body as string)).toEqual({
		thread_id: "thread-test-uuid",
		message: "hi there",
	});
});
```

- [ ] **Step 2: Run and verify pass**

```bash
pnpm --dir web test ask
```

Expected: 2 pass.

- [ ] **Step 3: Commit**

```bash
git add web/app/__tests__/ask.test.tsx
git commit -m "test(web): cover streaming tokens into ChatView"
```

---

### Task 11: Tool-status frame surfaces ephemeral label

**Files:**
- Modify: `web/app/__tests__/ask.test.tsx`

- [ ] **Step 1: Add the test**

```tsx
it("renders an ephemeral status line while a tool frame is in flight", async () => {
	const fetchMock = vi.fn().mockResolvedValueOnce(
		streamingResponse(
			streamFrom(
				'data: {"type":"tool","content":"query_tube_status"}\n\n',
				'data: {"type":"token","content":"Result"}\n\n',
				'data: {"type":"end","content":""}\n\n',
			),
		),
	);
	vi.stubGlobal("fetch", fetchMock);

	render(<AskPage />);

	fireEvent.change(screen.getByLabelText(/message/i), {
		target: { value: "status?" },
	});
	fireEvent.submit(screen.getByLabelText(/message/i).closest("form")!);

	// After the stream finishes, status must be cleared.
	await screen.findByText(/result/i);
	expect(screen.queryByTestId("agent-status")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify pass**

```bash
pnpm --dir web test ask
```

Expected: 3 pass.

- [ ] **Step 3: Commit**

```bash
git add web/app/__tests__/ask.test.tsx
git commit -m "test(web): cover tool status lifecycle in ChatView"
```

---

### Task 12: 503 surfaces top-of-card alert

**Files:**
- Modify: `web/app/__tests__/ask.test.tsx`

- [ ] **Step 1: Add the test**

```tsx
it("surfaces a service alert when the agent endpoint returns 503", async () => {
	const fetchMock = vi.fn().mockResolvedValueOnce(
		new Response(JSON.stringify({ detail: "agent unavailable" }), {
			status: 503,
			headers: { "content-type": "application/problem+json" },
		}),
	);
	vi.stubGlobal("fetch", fetchMock);

	render(<AskPage />);

	fireEvent.change(screen.getByLabelText(/message/i), {
		target: { value: "anything" },
	});
	fireEvent.submit(screen.getByLabelText(/message/i).closest("form")!);

	expect(await screen.findByText(/agent unavailable/i)).toBeInTheDocument();
	expect(
		screen.queryByTestId("conversation"),
	).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify pass**

```bash
pnpm --dir web test ask
```

Expected: 4 pass.

- [ ] **Step 3: Commit**

```bash
git add web/app/__tests__/ask.test.tsx
git commit -m "test(web): cover 503 alert path in ChatView"
```

---

### Task 13: mid-stream `end:error` flags the bubble

**Files:**
- Modify: `web/app/__tests__/ask.test.tsx`

- [ ] **Step 1: Add the test**

```tsx
it("flags the assistant bubble when the stream ends with an error", async () => {
	const fetchMock = vi.fn().mockResolvedValueOnce(
		streamingResponse(
			streamFrom(
				'data: {"type":"token","content":"Partial "}\n\n',
				'data: {"type":"end","content":"error"}\n\n',
			),
		),
	);
	vi.stubGlobal("fetch", fetchMock);

	render(<AskPage />);

	fireEvent.change(screen.getByLabelText(/message/i), {
		target: { value: "go" },
	});
	fireEvent.submit(screen.getByLabelText(/message/i).closest("form")!);

	await screen.findByText(/partial/i);

	const assistantBubble = screen
		.getByTestId("conversation")
		.querySelector('[data-role="assistant"]');
	expect(assistantBubble).toHaveAttribute("data-errored", "true");
});
```

- [ ] **Step 2: Run and verify pass**

```bash
pnpm --dir web test ask
```

Expected: 5 pass.

- [ ] **Step 3: Commit**

```bash
git add web/app/__tests__/ask.test.tsx
git commit -m "test(web): cover end:error bubble flag in ChatView"
```

---

## Phase 4 — Landing page link + final wiring

### Task 14: Add the "Ask the agent →" link to the landing page

**Files:**
- Modify: `web/app/page.tsx`

- [ ] **Step 1: Edit the header block in `web/app/page.tsx`**

Replace the existing `<header>` element (lines 74–81 of the current file) with:

```tsx
				<header className="flex flex-col gap-2">
					<div className="flex flex-wrap items-baseline justify-between gap-2">
						<h1 className="font-heading text-2xl font-semibold tracking-tight">
							Network Now
						</h1>
						<a
							href="/ask"
							className="text-sm font-medium text-primary underline-offset-4 hover:underline"
						>
							Ask the agent →
						</a>
					</div>
					<p className="text-sm text-muted-foreground">
						Live operational status across the served TfL lines.
					</p>
				</header>
```

- [ ] **Step 2: Verify lint and existing landing tests still pass**

```bash
pnpm --dir web lint
pnpm --dir web test
```

Expected: all green (existing `network-now.test.tsx` does not lock the header markup beyond the heading text).

- [ ] **Step 3: Commit**

```bash
git add web/app/page.tsx
git commit -m "feat(web): link Ask page from the landing header"
```

---

### Task 15: Final pre-push gate

**Files:** none (verification only)

- [ ] **Step 1: Run `make check`**

```bash
make check
```

Expected: all six steps pass — `uv run task lint`, `uv run task test`, `uv run task dbt-parse`, `pnpm --dir web lint`, `pnpm --dir web test`, `pnpm --dir web build`.

- [ ] **Step 2: If anything fails, stop and report**

If `pnpm --dir web build` reports a missing module from `crypto.randomUUID()` typing or the `@/` alias, re-run with `pnpm --dir web exec tsc --noEmit` to isolate the type error before patching.

- [ ] **Step 3: Update PROGRESS.md**

In the `TM-E3` row of `PROGRESS.md`, set status to `✅ <today>` with a short note summarising the wiring. Match the prose density of the TM-E2 row.

- [ ] **Step 4: Commit progress update**

```bash
git add PROGRESS.md
git commit -m "docs(progress): mark TM-E3 done"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin feature/TM-E3-chat-view
gh pr create --title "feat(web): TM-E3 chat view with SSE streaming" --body "Closes TM-E3. Streams /chat/stream into a client ChatView with tool status, error alerts, and end:error bubble flagging. No new dependencies."
```

---

## Success criteria

### Automated

1. `pnpm --dir web test web/lib/sse-parser.test.ts` — all parser cases pass.
2. `pnpm --dir web test web/lib/api/chat-stream.test.ts` — all fetcher cases pass.
3. `pnpm --dir web test web/app/__tests__/ask.test.tsx` — all five client-component cases pass.
4. `pnpm --dir web lint` — Biome clean, no new ignores.
5. `pnpm --dir web build` — Next.js production build succeeds with the new client component (the `"use client"` boundary on `ChatView` is the only client island in `/ask`).
6. `make check` — green end-to-end.

### Manual

1. With the API running locally and `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `PINECONE_API_KEY` set, asking "How is the Piccadilly line right now?" in the Ask page renders incremental tokens within ~2 s.
2. The "Using tool: <name>…" status appears for tool-using queries and disappears once the first answer token arrives.
3. With the API up but the agent keys unset, the Ask page renders the "Agent unavailable" alert at the top with the RFC 7807 detail string. No assistant bubble is left dangling in the conversation.
4. Closing the browser tab mid-stream does not throw any console error in the Next.js dev console (the generator's `try/finally` releases the reader cleanly).
5. The landing page header shows "Ask the agent →" and clicking it navigates to `/ask`.

---

## What we're NOT doing

- **No history endpoint integration.** `/api/v1/chat/{thread_id}/history` is left unconsumed; thread state is per-mount.
- **No localStorage / sessionStorage persistence.** Refreshing the page starts a new thread.
- **No shared `nav.tsx` component.** The link from landing → `/ask` is a single anchor; a real nav comes with TM-E4 / TM-F1 if needed.
- **No new dependencies.** `react-markdown`, `@microsoft/fetch-event-source`, `zustand`, `swr`, `@testing-library/user-event` — all out of scope.
- **No ADR.** Every choice (raw fetch, custom parser, plain text rendering) stays inside the existing tech stack lock.
- **No backend changes.** All TM-E3 work is in `web/`.
- **No E2E test (Playwright).** Component-level smoke tests with mocked `ReadableStream` cover the wiring; full browser tests are deferred to TM-F1.
- **No reconnect-on-disconnect logic.** If the connection drops mid-stream the user gets a flagged bubble and can resubmit. Auto-retry is YAGNI for a portfolio demo.
- **No `AbortController` UX (cancel button).** The generator accepts a `signal`, but the UI does not wire one — adding a Stop button is a future polish item.
- **No markdown / citation formatting.** The agent prompt may include "Source: …" lines; these render as plain text.
- **No reliability page.** `web/app/reliability/page.tsx` stays placeholder.
