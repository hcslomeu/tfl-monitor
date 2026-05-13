import { render, screen } from "@testing-library/react";

import { TopNav } from "../top-nav";

describe("TopNav", () => {
	it("renders brand, repo link, and status summary segments", () => {
		render(
			<TopNav
				summary={{ good: 11, minor: 2, severe: 1, suspended: 1 }}
				clockLabel="18:42 BST · live"
			/>,
		);

		expect(screen.getByText("TfL Monitor")).toBeInTheDocument();
		expect(screen.getByText(/11 good/)).toBeInTheDocument();
		expect(screen.getByText(/2 minor/)).toBeInTheDocument();
		expect(screen.getByText(/1 severe/)).toBeInTheDocument();
		expect(screen.getByText(/1 suspended/)).toBeInTheDocument();
		expect(screen.getByText("18:42 BST · live")).toBeInTheDocument();

		const link = screen.getByRole("link", { name: /github repo/i });
		expect(link).toHaveAttribute(
			"href",
			"https://github.com/humbertolomeu/tfl-monitor",
		);
	});
});
