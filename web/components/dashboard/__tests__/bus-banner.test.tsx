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
});
