import type { NewsItem } from "@/components/dashboard/types";

/**
 * News-and-reports fixtures sourced from the design-system canvas's
 * `TFL_NEWS` array (`Humberto Lomeu Design System/ui_kits/tfl_monitor/
 * Components.jsx`).
 */
export const MOCK_NEWS: NewsItem[] = [
	{
		time: "17:58",
		title: "Elizabeth line — westbound severe delays",
		body: "Faulty train at Hayes & Harlington. Tickets accepted on Piccadilly & Bakerloo.",
	},
	{
		time: "16:20",
		title: "Northern line — Bank branch part-suspended",
		body: "No service between Kennington and Moorgate until further notice.",
	},
	{
		time: "14:05",
		title: "Planned engineering — weekend",
		body: "District line no service Earl’s Court ↔ Wimbledon Sat – Sun. Replacement buses run.",
	},
];
