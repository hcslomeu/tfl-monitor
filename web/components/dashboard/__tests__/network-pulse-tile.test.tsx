import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NetworkPulseTile } from "@/components/dashboard/network-pulse-tile";
import type { LineStatus } from "@/lib/api/status-live";

function line(
	overrides: Partial<LineStatus> & {
		line_id: string;
		mode: LineStatus["mode"];
	},
): LineStatus {
	return {
		line_id: overrides.line_id,
		line_name: overrides.line_id,
		mode: overrides.mode,
		status_severity: overrides.status_severity ?? 10,
		status_severity_description:
			overrides.status_severity_description ?? "Good Service",
		reason: overrides.reason ?? null,
		valid_from: overrides.valid_from ?? "2026-05-03T00:00:00Z",
		valid_to: overrides.valid_to ?? "2026-05-03T23:59:59Z",
	};
}

describe("<NetworkPulseTile>", () => {
	it("renders the Tube fraction headline", () => {
		const lines = [
			line({ line_id: "bakerloo", mode: "tube", status_severity: 6 }),
			line({ line_id: "central", mode: "tube", status_severity: 10 }),
			line({ line_id: "circle", mode: "tube", status_severity: 10 }),
		];
		render(<NetworkPulseTile lines={lines} />);

		expect(screen.getAllByText(/2 of 3/).length).toBeGreaterThan(0);
		expect(screen.getByText(/Tube lines/i)).toBeInTheDocument();
	});

	it("counts good-service across all modes for the cross-mode total", () => {
		const lines = [
			line({ line_id: "bakerloo", mode: "tube", status_severity: 10 }),
			line({ line_id: "12", mode: "bus", status_severity: 10 }),
			line({ line_id: "ncn", mode: "bus", status_severity: 6 }),
		];
		render(<NetworkPulseTile lines={lines} />);

		expect(screen.getByText(/2 of 3/i)).toBeInTheDocument();
		expect(screen.getByText(/all modes/i)).toBeInTheDocument();
	});

	it("buckets severities into red/amber/green tally with TfL boundaries", () => {
		const lines = [
			line({ line_id: "a", mode: "tube", status_severity: 0 }),
			line({ line_id: "b", mode: "tube", status_severity: 6 }),
			line({ line_id: "c", mode: "tube", status_severity: 9 }),
			line({ line_id: "d", mode: "tube", status_severity: 10 }),
			line({ line_id: "e", mode: "tube", status_severity: 18 }),
			line({ line_id: "f", mode: "tube", status_severity: 19 }),
		];
		render(<NetworkPulseTile lines={lines} />);

		expect(screen.getByLabelText(/severe lines: 2/i)).toBeInTheDocument();
		expect(screen.getByLabelText(/degraded lines: 1/i)).toBeInTheDocument();
		expect(screen.getByLabelText(/good lines: 2/i)).toBeInTheDocument();
	});

	it("renders zero-state when no lines are reported", () => {
		render(<NetworkPulseTile lines={[]} />);

		expect(screen.getAllByText(/0 of 0/).length).toBeGreaterThan(0);
	});
});
