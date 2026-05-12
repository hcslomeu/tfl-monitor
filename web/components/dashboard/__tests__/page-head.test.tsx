import { render, screen } from "@testing-library/react";

import { PageHead } from "../page-head";

describe("PageHead", () => {
	it("renders title and meta line", () => {
		render(
			<PageHead
				lineCount={15}
				lastRefreshedLabel="18:42:14 BST"
				refreshIntervalSeconds={30}
			/>,
		);

		expect(
			screen.getByRole("heading", { name: /london transport — at a glance/i }),
		).toBeInTheDocument();
		expect(
			screen.getByText(
				/15 lines · last refreshed 18:42:14 BST · auto-refresh every 30s/,
			),
		).toBeInTheDocument();
	});
});
