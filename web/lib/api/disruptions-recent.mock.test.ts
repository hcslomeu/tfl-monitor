import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("getRecentDisruptions — USE_MOCKS branch", () => {
	const fetchMock = vi.fn();

	beforeEach(() => {
		fetchMock.mockReset();
		vi.stubGlobal("fetch", fetchMock);
		vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "true");
		vi.resetModules();
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.unstubAllEnvs();
		vi.resetModules();
	});

	it("short-circuits to a single fixture without calling fetch", async () => {
		const { getRecentDisruptions } = await import("./disruptions-recent");

		const result = await getRecentDisruptions();

		expect(fetchMock).not.toHaveBeenCalled();
		expect(result).toHaveLength(1);
		const [first] = result;
		expect(first.affected_routes).toContain("elizabeth");
		expect(first.affected_stops.length).toBeGreaterThan(0);
		expect(first.summary).toMatch(/Paddington/);
	});
});
