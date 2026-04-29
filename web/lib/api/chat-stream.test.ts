import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import type { Frame } from "@/lib/sse-parser";
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
