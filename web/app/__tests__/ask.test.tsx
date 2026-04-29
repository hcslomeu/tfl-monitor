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
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(
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
		const form = screen.getByLabelText(/message/i).closest("form");
		if (!form) throw new Error("form not found");
		fireEvent.submit(form);

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

	it("renders an ephemeral status line while a tool frame is in flight", async () => {
		// Drive the stream in two phases so we can assert the status appears
		// before the first token clears it. A plain `streamFrom(...)` enqueues
		// every chunk synchronously and closes — by the time the consumer reads,
		// the token has already overwritten the status, so the transient render
		// is invisible. Manual controller lets us pause between chunks.
		let controller!: ReadableStreamDefaultController<Uint8Array>;
		const stream = new ReadableStream<Uint8Array>({
			start(c) {
				controller = c;
			},
		});
		const fetchMock = vi.fn().mockResolvedValueOnce(streamingResponse(stream));
		vi.stubGlobal("fetch", fetchMock);

		render(<AskPage />);

		fireEvent.change(screen.getByLabelText(/message/i), {
			target: { value: "status?" },
		});
		const form = screen.getByLabelText(/message/i).closest("form");
		if (!form) throw new Error("form not found");
		fireEvent.submit(form);

		const enc = new TextEncoder();
		controller.enqueue(
			enc.encode('data: {"type":"tool","content":"query_tube_status"}\n\n'),
		);

		const status = await screen.findByTestId("agent-status");
		expect(status).toHaveTextContent(/query_tube_status/);

		controller.enqueue(
			enc.encode('data: {"type":"token","content":"Result"}\n\n'),
		);
		controller.enqueue(enc.encode('data: {"type":"end","content":""}\n\n'));
		controller.close();

		await screen.findByText(/result/i);
		expect(screen.queryByTestId("agent-status")).not.toBeInTheDocument();
	});

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
		const form = screen.getByLabelText(/message/i).closest("form");
		if (!form) throw new Error("form not found");
		fireEvent.submit(form);

		const alert = await screen.findByRole("alert");
		expect(alert).toHaveTextContent(/agent unavailable/i);
		expect(screen.queryByTestId("conversation")).not.toBeInTheDocument();
	});

	it("flags the assistant bubble when the stream ends with an error", async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(
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
		const form = screen.getByLabelText(/message/i).closest("form");
		if (!form) throw new Error("form not found");
		fireEvent.submit(form);

		await screen.findByText(/partial/i);

		const assistantBubble = screen
			.getByTestId("conversation")
			.querySelector('[data-role="assistant"]');
		expect(assistantBubble).toHaveAttribute("data-errored", "true");
	});
});
