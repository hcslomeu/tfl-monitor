import { lineColorByName } from "@/lib/dashboard/adapt";
import type { components } from "@/lib/types";

export type ArrivalsView = components["schemas"]["ArrivalsView"];

/** Format seconds-to-arrival as a board countdown ("due" / "N min"). */
function countdown(seconds: number): string {
	if (seconds < 60) return "due";
	return `${Math.round(seconds / 60)} min`;
}

/**
 * Render next arrivals as a platform-grouped board.
 *
 * The backend `arrivals` frame carries a station and platforms, each
 * with up to five predictions `{line, destination, seconds}` ordered by
 * time to arrival. Each row colours a line dot via the shared TfL
 * palette and shows the destination and a countdown.
 */
export function ArrivalsBoard({ view }: { view: ArrivalsView }) {
	return (
		<div className="tfl-arrivals" data-testid="arrivals-board">
			<div className="tfl-arrivals-head">
				<span className="tfl-arrivals-title">{view.station}</span>
				<span className="tfl-arrivals-sub">next arrivals</span>
			</div>
			{view.platforms.map((platform) => (
				<div className="tfl-arrivals-platform" key={platform.platform}>
					<span className="tfl-arrivals-plat-label">{platform.platform}</span>
					<ul className="tfl-arrivals-rows">
						{platform.arrivals.map((arrival, i) => (
							<li
								// biome-ignore lint/suspicious/noArrayIndexKey: predictions have no stable id and order is fixed for a given result.
								key={i}
								className="tfl-arrivals-row"
							>
								<span
									className="tfl-arrivals-dot"
									style={{ background: lineColorByName(arrival.line) }}
									aria-hidden
								/>
								<span className="tfl-arrivals-line">{arrival.line}</span>
								<span className="tfl-arrivals-dest">
									{arrival.destination ?? "—"}
								</span>
								<span className="tfl-arrivals-eta">
									{countdown(arrival.seconds)}
								</span>
							</li>
						))}
					</ul>
				</div>
			))}
		</div>
	);
}
