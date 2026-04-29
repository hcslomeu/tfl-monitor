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
