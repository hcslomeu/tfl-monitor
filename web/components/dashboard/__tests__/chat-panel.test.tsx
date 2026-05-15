import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "../chat-panel";

const encoder = new TextEncoder();

function streamFrom(...chunks: string[]): ReadableStream<Uint8Array> {
	return new ReadableStream({
		start(controller) {
			for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
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

function typeIntoTextbox(value: string): HTMLTextAreaElement {
	const textbox = screen.getByRole("textbox") as HTMLTextAreaElement;
	fireEvent.change(textbox, { target: { value } });
	return textbox;
}

function clickSend(): void {
	fireEvent.click(screen.getByRole("button", { name: /send/i }));
}

describe("ChatPanel (TM-F2 SSE rewrite)", () => {
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

	it("renders the chat shell with the send button disabled while empty", () => {
		render(<ChatPanel />);

		expect(
			screen.getByRole("heading", { name: /ask the monitor/i }),
		).toBeInTheDocument();
		expect(screen.getByRole("textbox")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
		expect(screen.queryByTestId("conversation")).not.toBeInTheDocument();
		expect(screen.queryByRole("alert")).not.toBeInTheDocument();
	});

	it("streams tokens into the assistant bubble after Send", async () => {
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

		render(<ChatPanel />);

		typeIntoTextbox("hi there");
		clickSend();

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

	it("surfaces an ephemeral tool-status line that clears on the first token", async () => {
		// Manual controller so the tool frame can land before the token frame
		// arrives — a single synchronous `streamFrom(...)` would have the token
		// overwrite the status before any render flush could observe it.
		let controller!: ReadableStreamDefaultController<Uint8Array>;
		const stream = new ReadableStream<Uint8Array>({
			start(c) {
				controller = c;
			},
		});
		const fetchMock = vi.fn().mockResolvedValueOnce(streamingResponse(stream));
		vi.stubGlobal("fetch", fetchMock);

		render(<ChatPanel />);

		typeIntoTextbox("status?");
		clickSend();

		controller.enqueue(
			encoder.encode('data: {"type":"tool","content":"query_tube_status"}\n\n'),
		);

		const status = await screen.findByTestId("agent-status");
		expect(status).toHaveTextContent(/query_tube_status/);

		controller.enqueue(
			encoder.encode('data: {"type":"token","content":"Result"}\n\n'),
		);
		controller.enqueue(encoder.encode('data: {"type":"end","content":""}\n\n'));
		controller.close();

		await screen.findByText(/result/i);
		expect(screen.queryByTestId("agent-status")).not.toBeInTheDocument();
	});

	it("rolls back the bubble pair and surfaces an alert on 503", async () => {
		const fetchMock = vi.fn().mockResolvedValueOnce(
			new Response(JSON.stringify({ detail: "agent unavailable" }), {
				status: 503,
				headers: { "content-type": "application/problem+json" },
			}),
		);
		vi.stubGlobal("fetch", fetchMock);

		render(<ChatPanel />);

		typeIntoTextbox("anything");
		clickSend();

		const alert = await screen.findByRole("alert");
		expect(alert).toHaveTextContent(/agent unavailable/i);
		expect(screen.queryByTestId("conversation")).not.toBeInTheDocument();
	});

	it("flags the assistant bubble with data-errored when the stream ends with an error frame", async () => {
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

		render(<ChatPanel />);

		typeIntoTextbox("go");
		clickSend();

		await screen.findByText(/partial/i);

		const assistantBubble = screen
			.getByTestId("conversation")
			.querySelector('[data-role="assistant"]');
		expect(assistantBubble).toHaveAttribute("data-errored", "true");
	});

	it("guards against a synchronous double-send before busy state flushes", async () => {
		// Manual controller so the in-flight stream is still open while we
		// fire the second click; the synchronous inFlightRef guard must
		// reject the second send before any second fetch can be issued.
		let controller!: ReadableStreamDefaultController<Uint8Array>;
		const stream = new ReadableStream<Uint8Array>({
			start(c) {
				controller = c;
			},
		});
		const fetchMock = vi.fn().mockResolvedValueOnce(streamingResponse(stream));
		vi.stubGlobal("fetch", fetchMock);

		render(<ChatPanel />);

		typeIntoTextbox("hi");
		clickSend();
		clickSend();

		controller.enqueue(
			encoder.encode('data: {"type":"token","content":"ok"}\n\n'),
		);
		controller.enqueue(encoder.encode('data: {"type":"end","content":""}\n\n'));
		controller.close();

		await screen.findByText(/ok/i);
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it("aborts the in-flight stream when the panel unmounts", async () => {
		const abortError = new DOMException("aborted", "AbortError");
		const fetchMock = vi
			.fn()
			.mockImplementation((_url: string, init: RequestInit) => {
				return new Promise((_resolve, reject) => {
					init.signal?.addEventListener("abort", () => reject(abortError));
				});
			});
		vi.stubGlobal("fetch", fetchMock);

		const { unmount } = render(<ChatPanel />);

		typeIntoTextbox("hi");
		clickSend();

		const init = fetchMock.mock.calls[0][1] as RequestInit;
		const signal = init.signal as AbortSignal;
		expect(signal.aborted).toBe(false);

		unmount();

		expect(signal.aborted).toBe(true);
	});
});
