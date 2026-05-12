import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/status-live", () => ({
	getStatusLive: vi.fn().mockResolvedValue([
		{
			line_id: "piccadilly",
			line_name: "Piccadilly",
			mode: "tube",
			status_severity: 6,
			status_severity_description: "Severe Delays",
			reason: "Signal failure",
			valid_from: "2026-05-03T00:00:00Z",
			valid_to: "2026-05-03T23:59:59Z",
		},
		{
			line_id: "central",
			line_name: "Central",
			mode: "tube",
			status_severity: 10,
			status_severity_description: "Good Service",
			reason: null,
			valid_from: "2026-05-03T00:00:00Z",
			valid_to: "2026-05-03T23:59:59Z",
		},
	]),
}));

vi.mock("@/lib/api/disruptions-recent", () => ({
	getRecentDisruptions: vi.fn().mockResolvedValue([
		{
			disruption_id: "rt-1",
			category: "RealTime",
			category_description: "Real Time",
			summary: "Severe delays on Piccadilly",
			description: "Signal failure at Acton Town.",
			affected_routes: ["Piccadilly"],
			affected_stops: [],
			closure_text: "",
			severity: 6,
			created: "2026-05-03T08:00:00Z",
			last_update: "2026-05-03T09:00:00Z",
		},
		{
			disruption_id: "pw-1",
			category: "PlannedWork",
			category_description: "Planned Work",
			summary: "Northern weekend closure",
			description: "Camden Town closed.",
			affected_routes: ["Northern"],
			affected_stops: [],
			closure_text: "",
			severity: 4,
			created: "2026-05-08T00:00:00Z",
			last_update: "2026-05-08T00:00:00Z",
		},
	]),
}));

vi.mock("@/components/chat-view", () => ({
	ChatView: () => <div data-testid="chat-view-stub" />,
}));

import HomePage from "@/app/page";

describe("HomePage (one-pager)", () => {
	beforeEach(() => {
		localStorage.clear();
	});
	afterEach(() => {
		vi.clearAllTimers();
	});

	it("renders all four dashboard cards plus the chat panel", async () => {
		render(<HomePage />);

		await waitFor(() => {
			expect(screen.getByText(/network status/i)).toBeInTheDocument();
		});

		expect(screen.getByText(/happening now/i)).toBeInTheDocument();
		expect(screen.getByText(/coming up/i)).toBeInTheDocument();
		expect(screen.getByText(/network pulse/i)).toBeInTheDocument();
		expect(
			screen.getAllByTestId("chat-view-stub").length,
		).toBeGreaterThanOrEqual(1);
	});

	it("surfaces the active disruption summary inside Happening now", async () => {
		render(<HomePage />);

		expect(
			await screen.findByText(/severe delays on piccadilly/i),
		).toBeInTheDocument();
	});

	it("renders the GitHub link in the header", async () => {
		render(<HomePage />);
		const link = await screen.findByRole("link", { name: /github/i });
		expect(link).toHaveAttribute("href", expect.stringContaining("github.com"));
	});
});
