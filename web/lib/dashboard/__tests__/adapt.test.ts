import { describe, expect, it } from "vitest";

import type { Disruption } from "@/lib/api/disruptions-recent";
import type { LineStatus } from "@/lib/api/status-live";
import {
	disruptionForLine,
	disruptionToSnapshot,
	lineStatusesToSummaries,
	severityToBucket,
	summarizeCounts,
} from "@/lib/dashboard/adapt";

const SAMPLE_LINES: LineStatus[] = [
	{
		line_id: "victoria",
		line_name: "Victoria",
		mode: "tube",
		status_severity: 10,
		status_severity_description: "Good Service",
		reason: null,
		valid_from: "2026-05-13T05:00:00Z",
		valid_to: "2026-05-13T23:59:00Z",
	},
	{
		line_id: "elizabeth",
		line_name: "Elizabeth line",
		mode: "elizabeth-line",
		status_severity: 6,
		status_severity_description: "Severe Delays",
		reason: null,
		valid_from: "2026-05-13T05:00:00Z",
		valid_to: "2026-05-13T23:59:00Z",
	},
];

describe("severityToBucket", () => {
	it("maps every observed severity to one of the four buckets", () => {
		expect(severityToBucket(10)).toBe("good");
		expect(severityToBucket(20)).toBe("good");
		expect(severityToBucket(9)).toBe("minor");
		expect(severityToBucket(7)).toBe("minor");
		expect(severityToBucket(6)).toBe("severe");
		expect(severityToBucket(4)).toBe("severe");
		expect(severityToBucket(1)).toBe("suspended");
		expect(severityToBucket(0)).toBe("suspended");
	});
});

describe("lineStatusesToSummaries", () => {
	it("joins backend ids with the dashboard registry", () => {
		const [victoria, elizabeth] = lineStatusesToSummaries(SAMPLE_LINES);

		expect(victoria).toMatchObject({
			code: "VIC",
			name: "Victoria",
			color: "#039BE5",
			status: "good",
			statusText: "Good Service",
		});
		expect(elizabeth).toMatchObject({
			code: "ELZ",
			name: "Elizabeth",
			color: "#6950A1",
			status: "severe",
		});
	});

	it("strips trailing ' line' so downstream components don't duplicate it", () => {
		const summaries = lineStatusesToSummaries([
			{
				...SAMPLE_LINES[0],
				line_id: "elizabeth",
				line_name: "Elizabeth line",
			},
			{
				...SAMPLE_LINES[0],
				line_id: "waterloo-city",
				line_name: "Waterloo & City",
			},
		]);
		expect(summaries[0].name).toBe("Elizabeth");
		expect(summaries[1].name).toBe("Waterloo & City");
	});

	it("falls back to a neutral meta when the line id is unknown", () => {
		const summaries = lineStatusesToSummaries([
			{
				...SAMPLE_LINES[0],
				line_id: "totally-new-line",
				line_name: "Mystery",
			},
		]);
		expect(summaries[0]).toMatchObject({ code: "TFL", color: "#5A6A77" });
	});
});

describe("summarizeCounts", () => {
	it("aggregates per-bucket totals", () => {
		const summaries = lineStatusesToSummaries(SAMPLE_LINES);
		expect(summarizeCounts(summaries)).toEqual({
			good: 1,
			minor: 0,
			severe: 1,
			suspended: 0,
		});
	});
});

describe("disruptionForLine + disruptionToSnapshot", () => {
	const disruption: Disruption = {
		disruption_id: "test-1",
		category: "RealTime",
		category_description: "Real Time",
		description: "Para 1.\n\nPara 2.",
		summary: "Severe delays westbound",
		affected_routes: ["elizabeth"],
		affected_stops: ["940GZZLUHBN"],
		closure_text: "",
		severity: 6,
		created: "2026-05-13T16:58:00Z",
		last_update: "2026-05-13T17:42:00Z",
	};

	it("resolves selected line via canonical id", () => {
		const [, elizabeth] = lineStatusesToSummaries(SAMPLE_LINES);
		expect(disruptionForLine([disruption], elizabeth)).toBe(disruption);
		const [victoria] = lineStatusesToSummaries(SAMPLE_LINES);
		expect(disruptionForLine([disruption], victoria)).toBeUndefined();
	});

	it("projects backend payload onto the snapshot view-model", () => {
		const snapshot = disruptionToSnapshot(disruption);
		expect(snapshot.headline).toBe("Severe delays westbound");
		expect(snapshot.body).toEqual(["Para 1.", "Para 2."]);
		expect(snapshot.stations).toEqual([
			{ name: "940GZZLUHBN", code: "940GZZLUHBN" },
		]);
		expect(snapshot.sourceLabel).toBe("Source: TfL Unified API");
		expect(snapshot.reportedAtLabel).toMatch(/\d{2}:\d{2}/);
		expect(snapshot.updatedAtLabel).toMatch(/\d{2}:\d{2}/);
	});
});
