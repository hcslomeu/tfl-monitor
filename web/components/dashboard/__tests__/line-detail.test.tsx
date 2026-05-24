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
	stations: [{ name: "Paddington", code: "PAD" }],
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
		// Resolved station name renders; the raw NaPTAN code is no longer
		// surfaced — the user-facing name carries all the signal.
		expect(screen.getByText("Paddington")).toBeInTheDocument();
		expect(screen.queryByText("PAD")).not.toBeInTheDocument();
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

	it("never renders the closure_text alert (collapsed in the redesign)", () => {
		render(
			<LineDetail
				line={LINE}
				disruption={{
					...DISRUPTION,
					closureText: "No service between Paddington and Reading.",
				}}
			/>,
		);

		expect(screen.queryByRole("alert")).not.toBeInTheDocument();
	});

	it("renders co-affected lines when affectedRoutes includes other lines", () => {
		render(
			<LineDetail
				line={LINE}
				disruption={{
					...DISRUPTION,
					affectedRoutes: ["piccadilly", "victoria"],
				}}
			/>,
		);

		const list = screen.getByRole("list", { name: /also affected/i });
		const items = list.querySelectorAll("li");
		expect(items).toHaveLength(2);
	});

	it("filters the current line out of the co-affected list", () => {
		render(
			<LineDetail
				line={LINE}
				disruption={{
					...DISRUPTION,
					// `elizabeth` is the current line; only `piccadilly` should
					// surface as a chip — the header already names Elizabeth.
					affectedRoutes: ["elizabeth", "piccadilly"],
				}}
			/>,
		);

		const list = screen.getByRole("list", { name: /also affected/i });
		const items = list.querySelectorAll("li");
		expect(items).toHaveLength(1);
		expect(items[0]).toHaveTextContent(/PIC/);
	});

	it("hides the block entirely when only the current line is affected", () => {
		render(
			<LineDetail
				line={LINE}
				disruption={{ ...DISRUPTION, affectedRoutes: ["elizabeth"] }}
			/>,
		);

		expect(
			screen.queryByRole("list", { name: /also affected/i }),
		).not.toBeInTheDocument();
	});

	it("does not render the co-affected block when affectedRoutes is absent", () => {
		render(<LineDetail line={LINE} disruption={DISRUPTION} />);

		expect(
			screen.queryByRole("list", { name: /also affected/i }),
		).not.toBeInTheDocument();
	});

	it("does not render the co-affected block when affectedRoutes is an empty array", () => {
		render(
			<LineDetail
				line={LINE}
				disruption={{ ...DISRUPTION, affectedRoutes: [] }}
			/>,
		);

		expect(
			screen.queryByRole("list", { name: /also affected/i }),
		).not.toBeInTheDocument();
	});
});
