import type { BusItem } from "@/components/dashboard/types";

/**
 * Bus-banner fixtures sourced from the design-system canvas's
 * `TFLBusBanner` block (`Humberto Lomeu Design System/ui_kits/
 * tfl_monitor/Components.jsx`).
 */
export const MOCK_BUSES: BusItem[] = [
	{
		route: "N29",
		text: "Diverted around Trafalgar Square — closure 19:00–22:00.",
	},
	{
		route: "38",
		text: "Stop closure at Piccadilly Circus, alight at Green Park.",
	},
	{ route: "73", text: "Running normally. No reported delays." },
	{ route: "N5", text: "Night service — start 23:30 from Edgware." },
];
