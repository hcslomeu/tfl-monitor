import { getLineMeta } from "@/lib/dashboard/adapt";

import type { DisruptionSnapshot, LineSummary } from "./types";

export type LineDetailState = "ready" | "loading" | "error";

export interface LineDetailProps {
	line: LineSummary;
	disruption?: DisruptionSnapshot;
	/**
	 * Presentation state for the card body. Defaults to `"ready"`, in which
	 * case the body is driven by `disruption` (rendered when present, "no
	 * reported disruption" copy when absent). `"loading"` and `"error"` show
	 * distinct non-jarring placeholders without flashing raw data.
	 */
	state?: LineDetailState;
}

export function LineDetail({
	line,
	disruption,
	state = "ready",
}: LineDetailProps) {
	const showDisruption = state === "ready" && disruption !== undefined;

	return (
		<section className="tfl-card">
			<div className="tfl-detail-h">
				<span
					className="tfl-detail-stripe"
					style={{ background: line.color }}
				/>
				<div>
					<h2 className="tfl-detail-name">{line.name} line</h2>
					<div className="tfl-detail-sub">
						{line.code} · {line.statusText} · {line.updatedLabel}
						{showDisruption ? ` · reported ${disruption.reportedAtLabel}` : ""}
					</div>
				</div>
			</div>
			{state === "loading" ? (
				<div className="tfl-disruption">
					<p>Loading line status…</p>
				</div>
			) : state === "error" ? (
				<div className="tfl-disruption">
					<p>Unable to load disruption details. Retrying shortly.</p>
				</div>
			) : disruption ? (
				<>
					<div className="tfl-disruption">
						<div className="summary">{disruption.headline}</div>
						{disruption.body.map((paragraph, index) => (
							// biome-ignore lint/suspicious/noArrayIndexKey: disruption body is a static prop with stable ordering; the index disambiguates duplicate paragraph strings that React would otherwise collide on.
							<p key={`${index}-${paragraph}`}>{paragraph}</p>
						))}
					</div>
					<AffectedRoutesChips
						currentLineCode={line.code}
						routes={disruption.affectedRoutes}
					/>
					{disruption.stations.length > 0 && (
						<div className="tfl-stations">
							<h5>Affected stations</h5>
							<ul aria-label="Affected stations">
								{disruption.stations.map((station) => (
									// `title` surfaces the full name on hover for
									// truncated rows (e.g. "Heathrow Terminals 2 & 3").
									<li key={station.code} title={station.name}>
										{station.name}
									</li>
								))}
							</ul>
						</div>
					)}
					<div className="tfl-detail-foot">
						<span>{disruption.sourceLabel}</span>
						<span>Updated {disruption.updatedAtLabel}</span>
					</div>
				</>
			) : (
				<div className="tfl-disruption">
					<p>No reported disruption.</p>
				</div>
			)}
		</section>
	);
}

interface AffectedRoutesChipsProps {
	currentLineCode: string;
	routes: readonly string[] | undefined;
}

/**
 * Renders co-affected lines as chips, excluding the current line. The
 * header card already names the line, so a single self-chip is pure
 * noise — collapse the whole block when no *other* lines are involved.
 */
function AffectedRoutesChips({
	currentLineCode,
	routes,
}: AffectedRoutesChipsProps) {
	if (!routes || routes.length === 0) return null;
	const currentCodeUpper = currentLineCode.toUpperCase();
	// Dedupe before filtering so a TfL payload that lists the same line
	// twice doesn't render duplicate chips with colliding React keys.
	const otherRoutes = Array.from(new Set(routes)).filter(
		(lineId) => getLineMeta(lineId).code.toUpperCase() !== currentCodeUpper,
	);
	if (otherRoutes.length === 0) return null;
	return (
		<div className="tfl-affected-routes">
			<h5>Also affected</h5>
			<ul aria-label="Also affected">
				{otherRoutes.map((lineId) => {
					const meta = getLineMeta(lineId);
					return (
						<li
							key={lineId}
							className="tfl-route-chip"
							style={{ borderColor: meta.color }}
						>
							<span
								className="tfl-route-chip-stripe"
								style={{ background: meta.color }}
							/>
							{meta.code}
						</li>
					);
				})}
			</ul>
		</div>
	);
}
