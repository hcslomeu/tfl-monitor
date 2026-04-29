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
});
