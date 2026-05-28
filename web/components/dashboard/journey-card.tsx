import type { components } from "@/lib/types";

export type JourneyView = components["schemas"]["JourneyView"];

const MODE_COLOR: Record<string, string> = {
	tube: "#0019A8",
	"elizabeth-line": "#6950A1",
	dlr: "#00AFAD",
	overground: "#EE7C0E",
	"national-rail": "#9B0058",
	bus: "#DC241F",
	tram: "#007D32",
	walking: "#8A8174",
};

const FALLBACK_MODE_COLOR = "#5A6A77";

/** Official TfL line colours, keyed by lowercase line name. */
const TUBE_LINE_COLOR: Record<string, string> = {
	bakerloo: "#B36305",
	central: "#E32017",
	circle: "#FFD300",
	district: "#00782A",
	"hammersmith & city": "#F3A9BB",
	jubilee: "#A0A5A9",
	metropolitan: "#9B0056",
	northern: "#000000",
	piccadilly: "#003688",
	victoria: "#0098D4",
	"waterloo & city": "#95CDBA",
};

function modeColor(mode: string): string {
	return MODE_COLOR[mode] ?? FALLBACK_MODE_COLOR;
}

/**
 * Pick a leg marker colour.
 *
 * Legs carry no line id, so tube legs are coloured from the line name in
 * the TfL summary ("Central line to Bank" → central → red), keeping the
 * marker in sync with the named line. Everything else falls back to its
 * mode colour.
 */
function legColor(mode: string, summary: string): string {
	if (mode === "tube") {
		const match = /^(.*?)\s+line\b/i.exec(summary);
		const lineColor = match && TUBE_LINE_COLOR[match[1].toLowerCase()];
		if (lineColor) {
			return lineColor;
		}
	}
	return modeColor(mode);
}

/** Pull "HH:MM" out of a naive (London-local) ISO timestamp. */
function clock(iso: string): string {
	const match = /T(\d{2}:\d{2})/.exec(iso);
	return match ? match[1] : "—";
}

function modeLabel(mode: string): string {
	return mode.replace(/-/g, " ");
}

/**
 * Render a planned journey as a vertical leg-by-leg timeline.
 *
 * The backend `journey` frame carries total duration, depart/arrive
 * clocks and per-leg `{mode, summary, minutes}`; there are no station
 * ids on the legs, so each leg shows a mode-coloured marker, the TfL
 * instruction summary, and its duration.
 */
export function JourneyCard({ view }: { view: JourneyView }) {
	return (
		<div className="tfl-journey" data-testid="journey-card">
			<div className="tfl-journey-head">
				<span className="tfl-journey-title">Journey</span>
				<span className="tfl-journey-total">{view.total_minutes} min</span>
			</div>
			<div className="tfl-journey-clocks">
				<span>{clock(view.start)}</span>
				<span className="tfl-journey-arrow" aria-hidden>
					→
				</span>
				<span>{clock(view.arrival)}</span>
			</div>
			<ol className="tfl-journey-legs">
				{view.legs.map((leg, i) => (
					<li
						// biome-ignore lint/suspicious/noArrayIndexKey: legs have no stable id and order is fixed for a given result.
						key={i}
						className="tfl-journey-leg"
					>
						<span
							className="tfl-journey-dot"
							style={{ background: legColor(leg.mode, leg.summary) }}
							aria-hidden
						/>
						<div className="tfl-journey-leg-body">
							<span className="tfl-journey-leg-mode">
								{modeLabel(leg.mode)}
							</span>
							<span className="tfl-journey-leg-summary">{leg.summary}</span>
						</div>
						<span className="tfl-journey-leg-min">{leg.minutes} min</span>
					</li>
				))}
			</ol>
		</div>
	);
}
