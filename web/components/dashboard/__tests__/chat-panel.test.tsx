import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { ChatPanel } from "../chat-panel";

describe("ChatPanel", () => {
	it("appends a user message on send and clears the input", async () => {
		const onSend = vi.fn();
		render(
			<ChatPanel
				initialMessages={[{ who: "bot", text: "Welcome to TfL Monitor" }]}
				onSend={onSend}
			/>,
		);

		expect(screen.getByText("Welcome to TfL Monitor")).toBeInTheDocument();

		const textarea = screen.getByRole("textbox");
		await userEvent.type(textarea, "What is the next train to Uxbridge?");
		await userEvent.click(screen.getByRole("button", { name: /send/i }));

		expect(
			screen.getByText("What is the next train to Uxbridge?"),
		).toBeInTheDocument();
		expect(textarea).toHaveValue("");
		expect(onSend).toHaveBeenCalledWith("What is the next train to Uxbridge?");
	});

	it("populates the textarea when a quick prompt chip is clicked", async () => {
		render(<ChatPanel />);

		const chip = screen.getByRole("button", { name: /next train/i });
		await userEvent.click(chip);

		expect(screen.getByRole("textbox")).toHaveValue(
			"Next train Baker Street → Uxbridge",
		);
	});
});
