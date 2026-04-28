import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import { type Disruption, getRecentDisruptions } from "./disruptions-recent";

const SAMPLE: Disruption[] = [
	{
		disruption_id: "2026-04-22-PIC-001",
		category: "RealTime",
		category_description: "Real Time",
		description: "Signal failure at Acton Town, reduced service on Piccadilly.",
		summary: "Severe delays on Piccadilly line",
		affected_routes: ["piccadilly"],
		affected_stops: ["940GZZLUATN", "940GZZLUACT"],
		closure_text: "",
		severity: 6,
		created: "2026-04-22T06:15:00Z",
		last_update: "2026-04-22T08:05:00Z",
	},
	{
		disruption_id: "2026-04-21-VIC-001",
		category: "PlannedWork",
		category_description: "Planned Work",
		description: "Engineering works affecting Victoria line weekend service.",
		summary: "Minor delays this weekend",
		affected_routes: ["victoria"],
		affected_stops: [],
		closure_text:
			"No service between Seven Sisters and Walthamstow Central on Sunday.",
		severity: 9,
		created: "2026-04-18T12:00:00Z",
		last_update: "2026-04-21T09:00:00Z",
	},
];

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "content-type": "application/json" },
	});
}

describe("getRecentDisruptions", () => {
	const fetchMock = vi.fn();

	beforeEach(() => {
		fetchMock.mockReset();
		vi.stubGlobal("fetch", fetchMock);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("calls /api/v1/disruptions/recent against the configured base URL", async () => {
		fetchMock.mockResolvedValueOnce(jsonResponse(SAMPLE));

		const result = await getRecentDisruptions();

		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toMatch(/\/api\/v1\/disruptions\/recent$/);
		expect(init?.headers).toMatchObject({ Accept: "application/json" });
		expect(init).toMatchObject({ cache: "no-store" });
		expect(result).toEqual(SAMPLE);
	});

	it("returns the parsed array preserving every required Disruption field", async () => {
		fetchMock.mockResolvedValueOnce(jsonResponse(SAMPLE));

		const disruptions = await getRecentDisruptions();

		for (const d of disruptions) {
			expect(d.disruption_id).toBeTypeOf("string");
			expect(d.category).toBeTypeOf("string");
			expect(d.category_description).toBeTypeOf("string");
			expect(d.summary).toBeTypeOf("string");
			expect(d.description).toBeTypeOf("string");
			expect(Array.isArray(d.affected_routes)).toBe(true);
			expect(Array.isArray(d.affected_stops)).toBe(true);
			expect(d.closure_text).toBeTypeOf("string");
			expect(d.severity).toBeGreaterThanOrEqual(0);
			expect(d.created).toBeTypeOf("string");
			expect(d.last_update).toBeTypeOf("string");
		}
	});

	it("returns an empty array when the API reports no rows", async () => {
		fetchMock.mockResolvedValueOnce(jsonResponse([]));

		await expect(getRecentDisruptions()).resolves.toEqual([]);
	});

	it("throws ApiError when the API returns a non-2xx response", async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponse({ detail: "warehouse offline" }, 503),
		);

		await expect(getRecentDisruptions()).rejects.toBeInstanceOf(ApiError);
	});

	it("propagates network failures so the caller can render a fallback", async () => {
		fetchMock.mockRejectedValueOnce(new TypeError("network down"));

		await expect(getRecentDisruptions()).rejects.toThrow(/network down/);
	});
});
