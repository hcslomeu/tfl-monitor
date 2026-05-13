import { render, screen } from "@testing-library/react";

import { NewsReports } from "../news-reports";

describe("NewsReports", () => {
	it("renders supplied items and pads empty slots up to the slot count", () => {
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
		expect(screen.getByText(/1 today/)).toBeInTheDocument();
		expect(screen.getAllByText(/No further updates/)).toHaveLength(2);
	});

	it("reports the full item count in the meta label even when slots truncate", () => {
		const items = Array.from({ length: 5 }, (_, i) => ({
			time: `0${i}:00`,
			title: `Report ${i}`,
			body: `Body ${i}`,
		}));

		render(<NewsReports items={items} slotCount={3} />);

		expect(screen.getByText(/5 today/)).toBeInTheDocument();
		expect(screen.queryByText(/3 today/)).not.toBeInTheDocument();
	});
});
