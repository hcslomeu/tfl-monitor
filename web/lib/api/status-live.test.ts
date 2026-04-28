import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import { getStatusLive, type LineStatus } from "./status-live";

const SAMPLE: LineStatus[] = [
	{
		line_id: "victoria",
		line_name: "Victoria",
		mode: "tube",
		status_severity: 10,
		status_severity_description: "Good Service",
		reason: null,
		valid_from: "2026-04-22T07:00:00Z",
		valid_to: "2026-04-22T23:59:59Z",
	},
	{
		line_id: "piccadilly",
		line_name: "Piccadilly",
		mode: "tube",
		status_severity: 6,
		status_severity_description: "Severe Delays",
		reason: "Signal failure at Acton Town",
		valid_from: "2026-04-22T06:15:00Z",
		valid_to: "2026-04-22T23:59:59Z",
	},
];

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "content-type": "application/json" },
	});
}

describe("getStatusLive", () => {
	const fetchMock = vi.fn();

	beforeEach(() => {
		fetchMock.mockReset();
		vi.stubGlobal("fetch", fetchMock);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("calls /api/v1/status/live against the configured base URL", async () => {
		fetchMock.mockResolvedValueOnce(jsonResponse(SAMPLE));

		const result = await getStatusLive();

		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0];
		expect(url).toMatch(/\/api\/v1\/status\/live$/);
		expect(init?.headers).toMatchObject({ Accept: "application/json" });
		expect(result).toEqual(SAMPLE);
	});

	it("returns the parsed array preserving every required LineStatus field", async () => {
		fetchMock.mockResolvedValueOnce(jsonResponse(SAMPLE));

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

	it("returns an empty array when the API reports no rows", async () => {
		fetchMock.mockResolvedValueOnce(jsonResponse([]));

		await expect(getStatusLive()).resolves.toEqual([]);
	});

	it("throws ApiError when the API returns a non-2xx response", async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponse({ detail: "warehouse offline" }, 503),
		);

		await expect(getStatusLive()).rejects.toBeInstanceOf(ApiError);
	});

	it("propagates network failures so the caller can render a fallback", async () => {
		fetchMock.mockRejectedValueOnce(new TypeError("network down"));

		await expect(getStatusLive()).rejects.toThrow(/network down/);
	});
});
