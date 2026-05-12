import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/chat-view", () => ({
	ChatView: () => <div data-testid="chat-view-stub">stub</div>,
}));

import { ChatPanel } from "@/components/dashboard/chat-panel";

describe("<ChatPanel>", () => {
	it("mounts ChatView inside the sticky aside on lg+", () => {
		render(<ChatPanel />);
		const stub = screen.getAllByTestId("chat-view-stub");
		expect(stub.length).toBeGreaterThanOrEqual(1);
	});

	it("opens the drawer when the FAB is clicked", async () => {
		const user = userEvent.setup();
		render(<ChatPanel />);

		const fab = screen.getByRole("button", { name: /open chat/i });
		await user.click(fab);

		expect(
			await screen.findByRole("dialog", { name: /ask the agent/i }),
		).toBeInTheDocument();
	});

	it("does not unmount the sticky ChatView when the drawer opens", async () => {
		const user = userEvent.setup();
		render(<ChatPanel />);

		const before = screen.getAllByTestId("chat-view-stub").length;
		const fab = screen.getByRole("button", { name: /open chat/i });
		await user.click(fab);

		const after = screen.getAllByTestId("chat-view-stub").length;
		expect(after).toBeGreaterThanOrEqual(before);
	});
});
