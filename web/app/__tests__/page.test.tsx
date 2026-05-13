import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Disruption } from "@/lib/api/disruptions-recent";
import type { LineStatus } from "@/lib/api/status-live";

const SAMPLE_LINES: LineStatus[] = [
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
		line_id: "piccadilly",
		line_name: "Piccadilly",
		mode: "tube",
		status_severity: 9,
		status_severity_description: "Minor Delays",
		reason: null,
		valid_from: "2026-05-13T05:00:00Z",
		valid_to: "2026-05-13T23:59:00Z",
	},
];

const SAMPLE_DISRUPTION: Disruption = {
	disruption_id: "ELZ-001",
	category: "RealTime",
	category_description: "Real Time",
	description: "Severe delays westbound between Paddington and Reading.",
	summary: "Severe delays westbound",
	affected_routes: ["elizabeth"],
	affected_stops: ["910GPADTON"],
	closure_text: "",
	severity: 6,
	created: "2026-05-13T16:58:00Z",
	last_update: "2026-05-13T17:42:00Z",
};

vi.mock("@/lib/api/status-live", async () => {
	const actual = await vi.importActual<typeof import("@/lib/api/status-live")>(
		"@/lib/api/status-live",
	);
	return {
		...actual,
		getStatusLive: vi.fn(async () => SAMPLE_LINES),
	};
});

vi.mock("@/lib/api/disruptions-recent", async () => {
	const actual = await vi.importActual<
		typeof import("@/lib/api/disruptions-recent")
	>("@/lib/api/disruptions-recent");
	return {
		...actual,
		getRecentDisruptions: vi.fn(async () => [SAMPLE_DISRUPTION]),
	};
});

describe("HomePage", () => {
	beforeEach(() => {
		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "visible",
		});
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it("renders the dashboard composition once mocked fetchers resolve", async () => {
		const { default: HomePage } = await import("../page");
		render(<HomePage />);

		expect(
			await screen.findByText(/Tube, Overground, DLR/),
		).toBeInTheDocument();

		expect(await screen.findByText("Elizabeth line")).toBeInTheDocument();

		expect(
			await screen.findByText(/What is the next train leaving Baker Street/),
		).toBeInTheDocument();

		const goodPill = await screen.findByText(/1 good/);
		expect(goodPill).toBeInTheDocument();
		expect(screen.getByText(/1 severe/)).toBeInTheDocument();
		expect(screen.getByText(/1 minor/)).toBeInTheDocument();
	});

	it("renders the news-and-reports + bus banner cards from mocks", async () => {
		const { default: HomePage } = await import("../page");
		render(<HomePage />);

		expect(
			await screen.findByText(/News & reports from TfL/),
		).toBeInTheDocument();
		expect(screen.getByText(/Buses worth knowing about/)).toBeInTheDocument();
	});
});
