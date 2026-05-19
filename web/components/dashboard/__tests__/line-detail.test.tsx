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

	it("surfaces the humanised relative updated label in the header", () => {
		render(<LineDetail line={LINE} disruption={DISRUPTION} />);

		expect(screen.getByText(/updated 2m ago/i)).toBeInTheDocument();
	});

	it("renders a positive empty state when no disruption is provided", () => {
		render(<LineDetail line={LINE} />);

		expect(screen.getByText("No reported disruption.")).toBeInTheDocument();
		expect(screen.queryByText("Affected stations")).not.toBeInTheDocument();
		expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
	});

	it("renders a distinct loading state", () => {
		render(<LineDetail line={LINE} state="loading" />);

		expect(screen.getByText(/Loading line status/i)).toBeInTheDocument();
		expect(
			screen.queryByText("No reported disruption."),
		).not.toBeInTheDocument();
		expect(screen.queryByText("Affected stations")).not.toBeInTheDocument();
	});

	it("renders a distinct error state without leaking disruption data", () => {
		render(<LineDetail line={LINE} disruption={DISRUPTION} state="error" />);

		expect(
			screen.getByText(/Unable to load disruption details/i),
		).toBeInTheDocument();
		// Even though a stale disruption was passed in, error state must hide it
		// to avoid mixing fresh-failure copy with stale data.
		expect(
			screen.queryByText(
				/Severe delays westbound between Paddington and Reading/,
			),
		).not.toBeInTheDocument();
		expect(screen.queryByText("Affected stations")).not.toBeInTheDocument();
	});
});
