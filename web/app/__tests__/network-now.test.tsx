import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NetworkNowPage from "@/app/page";

describe("Network Now page", () => {
	it("renders the page heading and the mock-data banner", async () => {
		const ui = await NetworkNowPage();
		render(ui);

		expect(
			screen.getByRole("heading", { name: /network now/i }),
		).toBeInTheDocument();
		expect(screen.getByText(/mock data/i)).toBeInTheDocument();
	});

	it("renders one card per mocked line", async () => {
		const ui = await NetworkNowPage();
		render(ui);

		expect(screen.getByText("Victoria")).toBeInTheDocument();
		expect(screen.getByText("Piccadilly")).toBeInTheDocument();
		expect(screen.getByText("Elizabeth line")).toBeInTheDocument();
	});

	it("colours the badge by severity band", async () => {
		const ui = await NetworkNowPage();
		render(ui);

		const goodService = screen.getByText("Good Service");
		const severeDelays = screen.getByText("Severe Delays");
		const minorDelays = screen.getByText("Minor Delays");

		expect(goodService).toHaveAttribute("data-tone", "good");
		expect(severeDelays).toHaveAttribute("data-tone", "severe");
		expect(minorDelays).toHaveAttribute("data-tone", "minor");
	});
});
