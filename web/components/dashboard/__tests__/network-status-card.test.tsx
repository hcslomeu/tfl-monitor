import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { NetworkStatusCard } from "@/components/dashboard/network-status-card";
import type { LineStatus } from "@/lib/api/status-live";

function line(
	id: string,
	mode: LineStatus["mode"],
	severity = 10,
	desc = "Good Service",
): LineStatus {
	return {
		line_id: id,
		line_name: id,
		mode,
		status_severity: severity,
		status_severity_description: desc,
		reason: null,
		valid_from: "2026-05-03T00:00:00Z",
		valid_to: "2026-05-03T23:59:59Z",
	};
}

describe("<NetworkStatusCard>", () => {
	beforeEach(() => {
		localStorage.clear();
	});
	afterEach(() => {
		localStorage.clear();
	});

	it("defaults to the Tube tab and renders only Tube lines", () => {
		const lines = [
			line("piccadilly", "tube"),
			line("12", "bus"),
			line("woolwich", "elizabeth-line"),
		];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		const grid = screen.getByRole("list", { name: /tube lines/i });
		const cells = within(grid).getAllByRole("listitem");
		expect(cells).toHaveLength(1);
		expect(cells[0]).toHaveTextContent("piccadilly");
	});

	it("switches mode on tab click and persists to localStorage", async () => {
		const user = userEvent.setup();
		const lines = [line("piccadilly", "tube"), line("12", "bus")];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		await user.click(screen.getByRole("tab", { name: /^bus$/i }));

		const grid = screen.getByRole("list", { name: /bus lines/i });
		expect(within(grid).getByText("12")).toBeInTheDocument();
		expect(localStorage.getItem("tfl-monitor:last-mode")).toBe("bus");
	});

	it("restores the last selected mode from localStorage on mount", () => {
		localStorage.setItem("tfl-monitor:last-mode", "elizabeth-line");
		const lines = [
			line("piccadilly", "tube"),
			line("woolwich", "elizabeth-line"),
		];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		const grid = screen.getByRole("list", { name: /elizabeth line lines/i });
		expect(within(grid).getByText("woolwich")).toBeInTheDocument();
	});

	it("falls back to Tube when localStorage holds a value not in the enum", () => {
		localStorage.setItem("tfl-monitor:last-mode", "spaceship");
		const lines = [line("piccadilly", "tube")];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		expect(
			screen.getByRole("list", { name: /tube lines/i }),
		).toBeInTheDocument();
	});

	it("shows an empty-state alert when the active mode has zero lines", async () => {
		const user = userEvent.setup();
		const lines = [line("piccadilly", "tube")];
		render(<NetworkStatusCard lines={lines} lastUpdated={null} />);

		await act(async () => {
			await user.click(screen.getByRole("tab", { name: /^bus$/i }));
		});

		expect(screen.getByText(/no lines reported/i)).toBeInTheDocument();
	});
});
