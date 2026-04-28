import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DisruptionsPage from "@/app/disruptions/page";
import type { Disruption } from "@/lib/api/disruptions-recent";
import { ApiError } from "@/lib/api-client";

vi.mock("@/lib/api/disruptions-recent", async () => {
	const actual = await vi.importActual<
		typeof import("@/lib/api/disruptions-recent")
	>("@/lib/api/disruptions-recent");
	return { ...actual, getRecentDisruptions: vi.fn() };
});

const { getRecentDisruptions } = await import("@/lib/api/disruptions-recent");
const getRecentDisruptionsMock = vi.mocked(getRecentDisruptions);

const SAMPLE: Disruption[] = [
	{
		disruption_id: "2026-04-22-PIC-001",
		category: "RealTime",
		category_description: "Real Time",
		description: "Signal failure at Acton Town, reduced service on Piccadilly.",
		summary: "Severe delays on Piccadilly line",
		affected_routes: ["piccadilly"],
		affected_stops: ["940GZZLUATN"],
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
	{
		disruption_id: "2026-04-22-VIC-002",
		category: "Information",
		category_description: "Information",
		description: "Reduced frequency during morning peak due to staff shortage.",
		summary: "Change of frequency on Victoria line",
		affected_routes: ["victoria"],
		affected_stops: [],
		closure_text: "",
		severity: 9,
		created: "2026-04-22T06:30:00Z",
		last_update: "2026-04-22T07:45:00Z",
	},
];

describe("Disruption Log page", () => {
	afterEach(() => {
		getRecentDisruptionsMock.mockReset();
	});

	it("renders one card per disruption returned by the API", async () => {
		getRecentDisruptionsMock.mockResolvedValueOnce(SAMPLE);

		const ui = await DisruptionsPage();
		render(ui);

		expect(
			screen.getByRole("heading", { name: /disruption log/i }),
		).toBeInTheDocument();
		expect(
			screen.getByText("Severe delays on Piccadilly line"),
		).toBeInTheDocument();
		expect(screen.getByText("Minor delays this weekend")).toBeInTheDocument();
		expect(
			screen.getByText("Change of frequency on Victoria line"),
		).toBeInTheDocument();
	});

	it("colours the category badge by tone", async () => {
		getRecentDisruptionsMock.mockResolvedValueOnce(SAMPLE);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.getByText("Real Time")).toHaveAttribute(
			"data-tone",
			"severe",
		);
		expect(screen.getByText("Planned Work")).toHaveAttribute(
			"data-tone",
			"minor",
		);
		expect(screen.getByText("Information")).toHaveAttribute(
			"data-tone",
			"info",
		);
	});

	it("renders the closure_text in a destructive alert when present", async () => {
		getRecentDisruptionsMock.mockResolvedValueOnce([SAMPLE[1]]);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.getByText("Closure")).toBeInTheDocument();
		expect(
			screen.getByText(
				/no service between seven sisters and walthamstow central on sunday/i,
			),
		).toBeInTheDocument();
	});

	it("hides the closure callout when closure_text is empty", async () => {
		getRecentDisruptionsMock.mockResolvedValueOnce([SAMPLE[0]]);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.queryByText("Closure")).not.toBeInTheDocument();
	});

	it("renders affected routes as badges", async () => {
		getRecentDisruptionsMock.mockResolvedValueOnce([SAMPLE[0]]);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.getByLabelText(/affected routes/i)).toBeInTheDocument();
		expect(screen.getByText("piccadilly")).toBeInTheDocument();
	});

	it("renders an empty-state alert when the API returns no rows", async () => {
		getRecentDisruptionsMock.mockResolvedValueOnce([]);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.getByText(/no disruptions reported/i)).toBeInTheDocument();
	});

	it("renders an error fallback when the API call rejects", async () => {
		getRecentDisruptionsMock.mockRejectedValueOnce(
			new ApiError(503, "warehouse offline"),
		);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
		expect(screen.getByText(/disruptions unavailable/i)).toBeInTheDocument();
		expect(screen.getByText(/warehouse offline/i)).toBeInTheDocument();
	});

	it("surfaces only the ApiError detail, not the technical message prefix", async () => {
		getRecentDisruptionsMock.mockRejectedValueOnce(
			new ApiError(503, "warehouse offline"),
		);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.queryByText(/tfl-monitor API/i)).not.toBeInTheDocument();
	});

	it("falls back to err.message for non-ApiError rejections", async () => {
		getRecentDisruptionsMock.mockRejectedValueOnce(
			new TypeError("network down"),
		);

		const ui = await DisruptionsPage();
		render(ui);

		expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
		expect(screen.getByText(/network down/i)).toBeInTheDocument();
	});
});
