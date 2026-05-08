import type { LineStatus } from "@/lib/api/status-live";

export type Mode = LineStatus["mode"];

/**
 * TfL brand-correct labels for each transport mode.
 *
 * The OpenAPI enum is kebab-case (`elizabeth-line`, `national-rail`, …).
 * `Elizabeth line` (lowercase 'l') and `National Rail` are correct per
 * TfL brand guidelines.
 */
export const MODE_LABELS: Record<Mode, string> = {
	tube: "Tube",
	"elizabeth-line": "Elizabeth line",
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
