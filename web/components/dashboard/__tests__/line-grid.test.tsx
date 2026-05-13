import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

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
});
