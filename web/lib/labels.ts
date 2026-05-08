import type { LineStatus } from "@/lib/api/status-live";

export type Mode = LineStatus["mode"];

/**
 * TfL brand-correct labels for each transport mode.
 *
 * The OpenAPI enum is kebab-case (`elizabeth-line`, `national-rail`, …);
 * blindly replacing hyphens and using Tailwind `capitalize` produces
 * `Elizabeth line` and `National rail`, which both miss the brand.
 */
export const MODE_LABELS: Record<Mode, string> = {
	tube: "Tube",
	"elizabeth-line": "Elizabeth Line",
	overground: "Overground",
	dlr: "DLR",
	bus: "Bus",
	"national-rail": "National Rail",
	"river-bus": "River Bus",
	"cable-car": "Cable Car",
	tram: "Tram",
};

export function modeLabel(mode: Mode): string {
	return MODE_LABELS[mode];
}
