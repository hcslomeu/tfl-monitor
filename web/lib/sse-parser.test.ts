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

	it("buffers a partial frame and emits it after the boundary arrives", () => {
		const parser = new SSEParser();

		const first = parser.push(bytes('data: {"type":"token","cont'));
		const second = parser.push(bytes('ent":"hello"}\n\n'));

		expect(first).toEqual<Frame[]>([]);
		expect(second).toEqual<Frame[]>([{ type: "token", content: "hello" }]);
	});

	it("ignores SSE comment lines (e.g. EventSourceResponse pings)", () => {
		const parser = new SSEParser();

		const frames = parser.push(
			bytes([": ping\n\n", 'data: {"type":"end","content":""}\n\n'].join("")),
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
});
