import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("getStatusLive — USE_MOCKS branch", () => {
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

	it("short-circuits to fixtures without calling fetch", async () => {
		const { getStatusLive } = await import("./status-live");

		const result = await getStatusLive();

		expect(fetchMock).not.toHaveBeenCalled();
		expect(result.length).toBe(14);
	});

	it("projects fixtures into the LineStatus schema", async () => {
		const { getStatusLive } = await import("./status-live");

		const lines = await getStatusLive();

		const elizabeth = lines.find((line) => line.line_id === "elizabeth");
		expect(elizabeth?.mode).toBe("elizabeth-line");
		expect(elizabeth?.status_severity_description).toBe("Severe Delays");

		const dlr = lines.find((line) => line.line_id === "dlr");
		expect(dlr?.mode).toBe("dlr");

		const bakerloo = lines.find((line) => line.line_id === "bakerloo");
		expect(bakerloo?.mode).toBe("tube");
		expect(bakerloo?.status_severity).toBe(10);

		expect(
			lines.find((line) => line.line_id === "waterloo-city"),
		).toBeDefined();
		expect(
			lines.find((line) => line.line_id === "london-overground"),
		).toBeDefined();

		for (const line of lines) {
			expect(line.valid_from).toBeTypeOf("string");
			expect(line.valid_to).toBeTypeOf("string");
		}
	});
});
