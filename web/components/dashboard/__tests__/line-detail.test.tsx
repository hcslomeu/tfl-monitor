import { render, screen } from "@testing-library/react";

import { LineDetail } from "../line-detail";
import type { DisruptionSnapshot, LineSummary } from "../types";

const LINE: LineSummary = {
	code: "ELZ",
	name: "Elizabeth",
	color: "#6950A1",
	status: "severe",
	statusText: "Severe delays",
	updatedLabel: "updated 2m ago",
};

const DISRUPTION: DisruptionSnapshot = {
	headline: "Severe delays westbound between Paddington and Reading",
	body: ["A faulty train at Hayes & Harlington is causing severe delays."],
	reportedAtLabel: "17:58 BST",
	stations: [{ name: "Paddington", code: "PAD", note: "interchange" }],
	sourceLabel: "Source: TfL Unified API",
	updatedAtLabel: "18:42:14 BST",
};

describe("LineDetail", () => {
	it("renders the line header and disruption details", () => {
		render(<LineDetail line={LINE} disruption={DISRUPTION} />);

		expect(
			screen.getByRole("heading", { name: /elizabeth line/i }),
		).toBeInTheDocument();
		expect(
			screen.getByText(
				/Severe delays westbound between Paddington and Reading/,
			),
		).toBeInTheDocument();
		expect(screen.getByText("Affected stations")).toBeInTheDocument();
		expect(screen.getByText(/PAD · interchange/)).toBeInTheDocument();
	});

	it("renders a fallback when no disruption is provided", () => {
		render(<LineDetail line={LINE} />);

		expect(
			screen.getByText(/No active disruption reported/i),
		).toBeInTheDocument();
		expect(screen.queryByText("Affected stations")).not.toBeInTheDocument();
	});
});
