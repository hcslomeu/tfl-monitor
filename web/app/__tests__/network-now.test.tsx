import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import NetworkNowPage from "@/app/page";
import type { LineStatus } from "@/lib/api/status-live";
import { ApiError } from "@/lib/api-client";

vi.mock("@/lib/api/status-live", async () => {
	const actual = await vi.importActual<typeof import("@/lib/api/status-live")>(
		"@/lib/api/status-live",
	);
	return { ...actual, getStatusLive: vi.fn() };
});

const { getStatusLive } = await import("@/lib/api/status-live");
const getStatusLiveMock = vi.mocked(getStatusLive);

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
	{
		line_id: "elizabeth",
		line_name: "Elizabeth line",
		mode: "elizabeth-line",
		status_severity: 9,
		status_severity_description: "Minor Delays",
		reason: "Earlier incident at Paddington",
		valid_from: "2026-04-22T05:30:00Z",
		valid_to: "2026-04-22T23:59:59Z",
	},
];

describe("Network Now page", () => {
	afterEach(() => {
		getStatusLiveMock.mockReset();
	});

	it("renders one card per line returned by the API", async () => {
		getStatusLiveMock.mockResolvedValueOnce(SAMPLE);

		const ui = await NetworkNowPage();
		render(ui);

		expect(
			screen.getByRole("heading", { name: /network now/i }),
		).toBeInTheDocument();
		expect(screen.getByText("Victoria")).toBeInTheDocument();
		expect(screen.getByText("Piccadilly")).toBeInTheDocument();
		expect(screen.getByText("Elizabeth line")).toBeInTheDocument();
	});

	it("colours the badge by severity band", async () => {
		getStatusLiveMock.mockResolvedValueOnce(SAMPLE);

		const ui = await NetworkNowPage();
		render(ui);

		expect(screen.getByText("Good Service")).toHaveAttribute(
			"data-tone",
			"good",
		);
		expect(screen.getByText("Severe Delays")).toHaveAttribute(
			"data-tone",
			"severe",
		);
		expect(screen.getByText("Minor Delays")).toHaveAttribute(
			"data-tone",
			"minor",
		);
	});

	it("renders an empty-state alert when the API returns no rows", async () => {
		getStatusLiveMock.mockResolvedValueOnce([]);

		const ui = await NetworkNowPage();
		render(ui);

		expect(screen.getByText(/no lines reported/i)).toBeInTheDocument();
	});

	it("renders an error fallback when the API call rejects", async () => {
		getStatusLiveMock.mockRejectedValueOnce(
			new ApiError(503, "warehouse offline"),
		);

		const ui = await NetworkNowPage();
		render(ui);

		expect(screen.getByRole("alert")).toBeInTheDocument();
		expect(screen.getByText(/live status unavailable/i)).toBeInTheDocument();
		expect(screen.getByText(/warehouse offline/i)).toBeInTheDocument();
	});
});
