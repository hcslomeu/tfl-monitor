import { describe, expect, it } from "vitest";

import { MODE_LABELS, modeLabel } from "@/lib/labels";

describe("modeLabel", () => {
	it("returns the brand-correct label for every TfL mode", () => {
		expect(modeLabel("tube")).toBe("Tube");
		expect(modeLabel("elizabeth-line")).toBe("Elizabeth line");
		expect(modeLabel("national-rail")).toBe("National Rail");
		expect(modeLabel("river-bus")).toBe("River Bus");
		expect(modeLabel("cable-car")).toBe("Cable Car");
	});

	it("exposes the same set of keys as the OpenAPI mode enum", () => {
		expect(Object.keys(MODE_LABELS).sort()).toEqual(
			[
				"bus",
				"cable-car",
				"dlr",
				"elizabeth-line",
				"national-rail",
				"overground",
				"river-bus",
				"tram",
				"tube",
			].sort(),
		);
	});
});
