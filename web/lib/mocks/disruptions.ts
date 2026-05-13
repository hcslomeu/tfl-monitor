import type { DisruptionSnapshot } from "@/components/dashboard/types";

/**
 * Elizabeth-line disruption snapshot used by `LineDetail` under
 * `USE_MOCKS`. Mirrors the inline copy from
 * `Humberto Lomeu Design System/ui_kits/tfl_monitor/Components.jsx`.
 */
export const MOCK_DISRUPTION: DisruptionSnapshot = {
	headline: "Severe delays westbound between Paddington and Reading",
	body: [
		"A faulty train at Hayes & Harlington is causing severe delays on the Elizabeth line westbound. Trains are reversing at Paddington. Eastbound services are running with minor delays.",
		"Tickets are being accepted on London Underground (Piccadilly, Bakerloo) and on TfL bus routes between Paddington and Heathrow.",
	],
	reportedAtLabel: "17:58 BST",
	stations: [
		{ name: "Paddington", code: "PAD", note: "interchange" },
		{ name: "Ealing Broadway", code: "EAL" },
		{ name: "West Ealing", code: "WEA" },
		{ name: "Hanwell", code: "HAN" },
		{ name: "Southall", code: "STL" },
		{ name: "Hayes & Harlington", code: "HAY", note: "incident" },
	],
	sourceLabel: "Source: TfL Unified API",
	updatedAtLabel: "18:42:14 BST",
};
