import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComingUpCard } from "@/components/dashboard/coming-up-card";
import type { Disruption } from "@/lib/api/disruptions-recent";

function disruption(
	over: Partial<Disruption> & { disruption_id: string },
): Disruption {
	return {
		disruption_id: over.disruption_id,
		category: over.category ?? "PlannedWork",
		category_description: over.category_description ?? "Planned Work",
		summary: over.summary ?? "Weekend closure",
		description: over.description ?? "",
		affected_routes: over.affected_routes ?? [],
		affected_stops: over.affected_stops ?? [],
		closure_text: over.closure_text ?? "",
		severity: over.severity ?? 6,
		created: over.created ?? "2026-05-03T00:00:00Z",
		last_update: over.last_update ?? "2026-05-03T00:00:00Z",
	};
}

describe("<ComingUpCard>", () => {
	it("filters to PlannedWork sorted by created ASC and caps at 5", () => {
		const items = [
			disruption({
				disruption_id: "rt",
				category: "RealTime",
				summary: "RT excluded",
			}),
			disruption({
				disruption_id: "1",
				created: "2026-05-08T00:00:00Z",
				summary: "May 8",
			}),
			disruption({
				disruption_id: "2",
				created: "2026-05-09T00:00:00Z",
				summary: "May 9",
			}),
			disruption({
				disruption_id: "3",
				created: "2026-05-15T00:00:00Z",
				summary: "May 15",
			}),
			disruption({
				disruption_id: "4",
				created: "2026-05-16T00:00:00Z",
				summary: "May 16",
			}),
			disruption({
				disruption_id: "5",
				created: "2026-05-17T00:00:00Z",
				summary: "May 17",
			}),
			disruption({
				disruption_id: "6",
				created: "2026-05-20T00:00:00Z",
				summary: "May 20 (capped out)",
			}),
		];
		render(<ComingUpCard disruptions={items} />);

		const list = screen.getByRole("list", { name: /upcoming/i });
		const rendered = within(list).getAllByRole("listitem");
		expect(rendered).toHaveLength(5);
		expect(rendered[0]).toHaveTextContent("May 8");
		expect(rendered[4]).toHaveTextContent("May 17");
		expect(screen.queryByText("RT excluded")).not.toBeInTheDocument();
		expect(screen.queryByText("May 20 (capped out)")).not.toBeInTheDocument();
	});

	it("shows a friendly empty state when there is no planned work", () => {
		render(<ComingUpCard disruptions={[]} />);

		expect(screen.getByText(/no planned work/i)).toBeInTheDocument();
	});

	it("ignores other categories entirely", () => {
		const items = [
			disruption({
				disruption_id: "a",
				category: "Information",
				summary: "Info note",
			}),
			disruption({
				disruption_id: "b",
				category: "Incident",
				summary: "Incident",
			}),
		];
		render(<ComingUpCard disruptions={items} />);

		expect(screen.getByText(/no planned work/i)).toBeInTheDocument();
	});
});
