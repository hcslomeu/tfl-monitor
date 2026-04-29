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
