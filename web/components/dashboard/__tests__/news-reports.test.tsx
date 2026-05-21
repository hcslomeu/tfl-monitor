import { render, screen } from "@testing-library/react";

import { NewsReports } from "../news-reports";

describe("NewsReports", () => {
	it("renders only the supplied items without padding empty slots", () => {
		// Pre-TM-28 the component padded the list up to `slotCount` with
		// "No further updates" placeholder rows. Now the list is a fixed-
		// height scroll surface, so empty rows would create dead space
		// when the warehouse has fewer than 5 fresh disruptions.
		render(
			<NewsReports
				items={[
					{
						time: "17:58",
						title: "Elizabeth line — westbound severe delays",
						body: "Faulty train at Hayes & Harlington.",
					},
				]}
			/>,
		);

		expect(
			screen.getByText(/Elizabeth line — westbound severe delays/),
		).toBeInTheDocument();
		expect(screen.getByText(/1 in last 12h/)).toBeInTheDocument();
		expect(screen.queryByText(/No further updates/)).not.toBeInTheDocument();
		expect(document.querySelectorAll(".tfl-news-list > li")).toHaveLength(1);
	});

	it("omits the body line when an item has no extra context to show", () => {
		render(
			<NewsReports
				items={[
					{
						time: "17:58",
						title: "Circle Line: Minor delays due to train cancellations.",
						body: "",
					},
				]}
			/>,
		);

		expect(
			screen.getByText(
				/Circle Line: Minor delays due to train cancellations\./,
			),
		).toBeInTheDocument();
		// No empty body div should leak through — only the title row.
		expect(document.querySelector(".tfl-news-body")).not.toBeInTheDocument();
	});

	it("renders an empty-state row when no disruptions are supplied", () => {
		// Cold-DB sentinel — the news pane should not look broken before
		// the first ingestion cycle has populated `disruptions_recent`.
		render(<NewsReports items={[]} />);

		expect(screen.getByText(/No recent updates/)).toBeInTheDocument();
		expect(screen.getByText(/0 in last 12h/)).toBeInTheDocument();
	});

	it("renders all supplied items beyond the visible window so the scroll surface stays populated", () => {
		// The visible window (max 5 rows) is enforced by CSS height +
		// overflow. The component must keep every item in the DOM so
		// the user can scroll to the older entries without re-fetching.
		const items = Array.from({ length: 8 }, (_, i) => ({
			time: `0${i}:00`,
			title: `Report ${i}`,
			body: `Body ${i}`,
		}));

		render(<NewsReports items={items} />);

		expect(screen.getByText(/8 in last 12h/)).toBeInTheDocument();
		expect(document.querySelectorAll(".tfl-news-list > li")).toHaveLength(8);
	});
});
