import { render, screen } from "@testing-library/react";

import { BusBanner } from "../bus-banner";

describe("BusBanner", () => {
	it("renders every bus cell and the route count", () => {
		render(
			<BusBanner
				buses={[
					{ route: "N29", text: "Diverted around Trafalgar Square." },
					{ route: "38", text: "Stop closure at Piccadilly Circus." },
				]}
			/>,
		);

		expect(screen.getByText("N29")).toBeInTheDocument();
		expect(screen.getByText("38")).toBeInTheDocument();
		expect(screen.getByText(/2 routes flagged/)).toBeInTheDocument();
	});

	it("labels the card as a Demo so reviewers don't mistake the fixtures for live data", () => {
		render(<BusBanner buses={[]} />);
		const demoPill = screen.getByText("Demo");
		expect(demoPill).toBeInTheDocument();
		expect(demoPill).toHaveAttribute(
			"title",
			"Bus disruptions are not in the live ingestion pipeline; this card uses static design-canvas fixtures so the layout stays visible end-to-end.",
		);
	});
});
