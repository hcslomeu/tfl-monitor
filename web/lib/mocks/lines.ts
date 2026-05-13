import type { LineSummary } from "@/components/dashboard/types";

/**
 * Static line-summary fixtures mirroring the design-system canvas.
 *
 * Sourced verbatim from `Humberto Lomeu Design System/ui_kits/tfl_monitor/
 * Components.jsx`'s `LINES` array. Used by the dashboard when
 * `USE_MOCKS` is on, and by the wrapped `getStatusLive` fetcher to
 * synthesise a backend-shaped response.
 */
export const MOCK_LINES: LineSummary[] = [
	{
		code: "BAK",
		name: "Bakerloo",
		color: "#894E24",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "CEN",
		name: "Central",
		color: "#DC241F",
		status: "minor",
		statusText: "Minor delays",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "CIR",
		name: "Circle",
		color: "#FFD329",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "DIS",
		name: "District",
		color: "#007D32",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "ELZ",
		name: "Elizabeth",
		color: "#6950A1",
		status: "severe",
		statusText: "Severe delays",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "HAM",
		name: "Hammersmith & City",
		color: "#E899A8",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "JUB",
		name: "Jubilee",
		color: "#7B868C",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "MET",
		name: "Metropolitan",
		color: "#751056",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "NTH",
		name: "Northern",
		color: "#000000",
		status: "minor",
		statusText: "Part suspended",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "PIC",
		name: "Piccadilly",
		color: "#0019A8",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "VIC",
		name: "Victoria",
		color: "#039BE5",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "WAT",
		name: "Waterloo & City",
		color: "#76D0BD",
		status: "suspended",
		statusText: "Suspended",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "DLR",
		name: "DLR",
		color: "#00AFAD",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
	{
		code: "OVG",
		name: "London Overground",
		color: "#EE7C0E",
		status: "good",
		statusText: "Good service",
		updatedLabel: "updated 2m ago",
	},
];
