import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/status-badge";

describe("StatusBadge severity bands", () => {
	it("renders severity 10 as good service", () => {
		render(<StatusBadge severity={10} description="Good Service" />);
		expect(screen.getByText("Good Service")).toHaveAttribute(
			"data-tone",
			"good",
		);
	});

	it.each([7, 8, 9])("renders severity %i as minor", (severity) => {
		render(
			<StatusBadge severity={severity} description={`band-${severity}`} />,
		);
		expect(screen.getByText(`band-${severity}`)).toHaveAttribute(
			"data-tone",
			"minor",
		);
	});

	it.each([
		0, 1, 5, 6,
	])("renders low severity %i as severe (delays / suspended)", (severity) => {
		render(
			<StatusBadge severity={severity} description={`band-${severity}`} />,
		);
		expect(screen.getByText(`band-${severity}`)).toHaveAttribute(
			"data-tone",
			"severe",
		);
	});

	// Codex P1 regression guard — severities 11..20 are progressively worse on
	// TfL's scale (11 = Part Closed, 20 = Service Closed). They must never
	// render as the green good-service tone.
	it.each([
		11, 13, 16, 20,
	])("renders high severity %i as severe (closed / planned closure)", (severity) => {
		render(
			<StatusBadge severity={severity} description={`band-${severity}`} />,
		);
		expect(screen.getByText(`band-${severity}`)).toHaveAttribute(
			"data-tone",
			"severe",
		);
	});
});
