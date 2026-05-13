import { describe, expect, it } from "vitest";

import { MOCK_BUSES } from "@/lib/mocks/buses";
import { MOCK_DISRUPTION } from "@/lib/mocks/disruptions";
import { MOCK_LINES } from "@/lib/mocks/lines";
import { MOCK_NEWS } from "@/lib/mocks/news";

describe("design-system mock fixtures", () => {
	it("ships 14 line summaries with unique codes", () => {
		expect(MOCK_LINES).toHaveLength(14);
		const codes = new Set(MOCK_LINES.map((line) => line.code));
		expect(codes.size).toBe(MOCK_LINES.length);
	});

	it("only uses known status buckets", () => {
		const allowed = new Set(["good", "minor", "severe", "suspended"]);
		for (const line of MOCK_LINES) {
			expect(allowed.has(line.status)).toBe(true);
		}
	});

	it("flags the Elizabeth line as the severe-delay subject", () => {
		const elizabeth = MOCK_LINES.find((line) => line.code === "ELZ");
		expect(elizabeth?.status).toBe("severe");
		expect(MOCK_DISRUPTION.headline).toMatch(/Elizabeth|Paddington|Reading/);
		expect(MOCK_DISRUPTION.body.length).toBeGreaterThan(0);
		expect(MOCK_DISRUPTION.stations.length).toBeGreaterThan(0);
	});

	it("ships 4 bus alerts and 3 news items per design canvas", () => {
		expect(MOCK_BUSES).toHaveLength(4);
		expect(MOCK_NEWS).toHaveLength(3);
	});
});
