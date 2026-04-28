import { describe, expect, it } from "vitest";

import { getStatusLive } from "./status-live";

describe("getStatusLive (mock)", () => {
	it("returns the committed fixture rows", async () => {
		const lines = await getStatusLive();
		expect(lines.length).toBeGreaterThan(0);
	});

	it("each row exposes every required LineStatus field", async () => {
		const lines = await getStatusLive();
		for (const line of lines) {
			expect(line.line_id).toBeTypeOf("string");
			expect(line.line_name).toBeTypeOf("string");
			expect(line.mode).toBeTypeOf("string");
			expect(line.status_severity_description).toBeTypeOf("string");
			expect(line.valid_from).toBeTypeOf("string");
			expect(line.valid_to).toBeTypeOf("string");
			expect(line.status_severity).toBeGreaterThanOrEqual(0);
			expect(line.status_severity).toBeLessThanOrEqual(20);
		}
	});

	it("includes the mock lines documented in the OpenAPI example", async () => {
		const lines = await getStatusLive();
		const ids = lines.map((line) => line.line_id);
		expect(ids).toContain("victoria");
		expect(ids).toContain("piccadilly");
		expect(ids).toContain("elizabeth");
	});
});
