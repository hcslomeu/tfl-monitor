import type { ChatMessage } from "@/components/dashboard/types";

/**
 * Seed transcript used by `ChatPanel` under `USE_MOCKS`.
 *
 * Mirrors the dialogue rendered in the design-system canvas
 * (`Humberto Lomeu Design System/ui_kits/tfl_monitor/Components.jsx`)
 * so the unauthenticated preview shows the conversational surface
 * in a useful, populated state.
 */
export const MOCK_CHAT_SEED: ChatMessage[] = [
	{
		who: "user",
		text: "What is the next train leaving Baker Street to Uxbridge?",
	},
	{
		who: "bot",
		text: "Next Metropolitan-line service: 18:46 from platform 2, calling at Finchley Road, Wembley Park, Harrow-on-the-Hill, then fast to Uxbridge. Journey time 38 min.",
	},
	{ who: "user", text: "Anything faster on the Piccadilly line?" },
	{
		who: "bot",
		text: "Piccadilly via Acton Town is slower (52 min). Stick with the Metropolitan.",
	},
];
