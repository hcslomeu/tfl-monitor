import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LineStatus } from "@/lib/api/status-live";
import { lineStatusesToSummaries } from "@/lib/dashboard/adapt";
import { LineGrid } from "../line-grid";
import type { LineSummary } from "../types";

const SAMPLE_LINES: LineSummary[] = [
	{
		code: "ELZ",
		name: "Elizabeth",
		color: "#6950A1",
		status: "severe",
		statusText: "Severe delays",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "VIC",
		name: "Victoria",
		color: "#039BE5",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 1m ago",
	},
];

function lineStatus(
	overrides: Partial<LineStatus> &
		Pick<LineStatus, "line_id" | "line_name" | "mode">,
): LineStatus {
	return {
		status_severity: 10,
		status_severity_description: "Good Service",
		reason: null,
		valid_from: "2026-05-13T05:00:00Z",
		valid_to: "2026-05-13T23:59:00Z",
		...overrides,
	};
}

describe("LineGrid", () => {
	it("renders each line and reports selection clicks", async () => {
		const onSelect = vi.fn();
		render(
			<LineGrid lines={SAMPLE_LINES} selected="ELZ" onSelect={onSelect} />,
		);

		expect(screen.getByText("Elizabeth")).toBeInTheDocument();
		expect(screen.getByText("Victoria")).toBeInTheDocument();
		expect(screen.getAllByText(/Severe delays/)[0]).toBeInTheDocument();

		const victoria = screen.getByText("Victoria").closest('[role="button"]');
		expect(victoria).not.toBeNull();
		if (victoria) {
			await userEvent.click(victoria);
		}
		expect(onSelect).toHaveBeenCalledWith("VIC");
	});

	it("renders tube → Elizabeth → DLR → Overground when fed adapter output", () => {
		const lines: LineStatus[] = [
			lineStatus({
				line_id: "windrush",
				line_name: "Windrush",
				mode: "overground",
			}),
			lineStatus({ line_id: "dlr", line_name: "DLR", mode: "dlr" }),
			lineStatus({ line_id: "victoria", line_name: "Victoria", mode: "tube" }),
			lineStatus({
				line_id: "elizabeth",
				line_name: "Elizabeth line",
				mode: "elizabeth-line",
			}),
			lineStatus({
				line_id: "piccadilly",
				line_name: "Piccadilly",
				mode: "tube",
			}),
			lineStatus({
				line_id: "lioness",
				line_name: "Lioness",
				mode: "overground",
			}),
		];
		const summaries = lineStatusesToSummaries(lines);

		const { container } = render(
			<LineGrid lines={summaries} onSelect={() => {}} />,
		);

		const renderedNames = Array.from(
			container.querySelectorAll(".tfl-line .tfl-line-name"),
		).map((node) => node.textContent ?? "");
		expect(renderedNames).toEqual([
			"Piccadilly",
			"Victoria",
			"Elizabeth",
			"DLR",
			"Lioness",
			"Windrush",
		]);
	});
});
