import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HappeningNowCard } from "@/components/dashboard/happening-now-card";
import type { Disruption } from "@/lib/api/disruptions-recent";

function disruption(
	over: Partial<Disruption> & { disruption_id: string },
): Disruption {
	return {
		disruption_id: over.disruption_id,
		category: over.category ?? "RealTime",
		category_description: over.category_description ?? "Real Time",
		summary: over.summary ?? "Severe delays",
		description: over.description ?? "Signal failure",
		affected_routes: over.affected_routes ?? [],
		affected_stops: over.affected_stops ?? [],
		closure_text: over.closure_text ?? "",
		severity: over.severity ?? 6,
		created: over.created ?? "2026-05-03T08:00:00Z",
		last_update: over.last_update ?? "2026-05-03T09:00:00Z",
	};
}

describe("<HappeningNowCard>", () => {
	it("renders only RealTime and Incident disruptions, sorted by last_update DESC", () => {
		const items: Disruption[] = [
			disruption({
				disruption_id: "a",
				category: "RealTime",
				summary: "Older RT",
				last_update: "2026-05-03T08:00:00Z",
			}),
			disruption({
				disruption_id: "b",
				category: "PlannedWork",
				summary: "Planned (excluded)",
			}),
			disruption({
				disruption_id: "c",
				category: "Incident",
				summary: "Latest incident",
				last_update: "2026-05-03T10:00:00Z",
			}),
		];
		render(<HappeningNowCard disruptions={items} />);

		const list = screen.getByRole("list", { name: /active disruptions/i });
		const rendered = within(list).getAllByRole("listitem");
		expect(rendered).toHaveLength(2);
		expect(rendered[0]).toHaveTextContent("Latest incident");
		expect(rendered[1]).toHaveTextContent("Older RT");
		expect(screen.queryByText("Planned (excluded)")).not.toBeInTheDocument();
	});

	it("shows a friendly empty state when nothing is happening", () => {
		render(<HappeningNowCard disruptions={[]} />);

		expect(screen.getByText(/all clear/i)).toBeInTheDocument();
	});

	it("surfaces closure_text in a destructive Alert", () => {
		const items = [
			disruption({
				disruption_id: "a",
				category: "RealTime",
				closure_text: "Aldgate–Baker St only",
			}),
		];
		render(<HappeningNowCard disruptions={items} />);

		expect(screen.getByText(/Aldgate–Baker St only/)).toBeInTheDocument();
	});

	it("renders affected_routes as outline badges", () => {
		const items = [
			disruption({
				disruption_id: "a",
				category: "RealTime",
				affected_routes: ["Piccadilly westbound", "Piccadilly eastbound"],
			}),
		];
		render(<HappeningNowCard disruptions={items} />);

		expect(screen.getByText("Piccadilly westbound")).toBeInTheDocument();
		expect(screen.getByText("Piccadilly eastbound")).toBeInTheDocument();
	});
});
