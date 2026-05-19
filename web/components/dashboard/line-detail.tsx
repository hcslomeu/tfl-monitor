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
					{disruption.stations.length > 0 && (
						<div className="tfl-stations">
							<h5>Affected stations</h5>
							<ul>
								{disruption.stations.map((station) => (
									<li key={station.code}>
										{station.name}{" "}
										<span className="code">
											{station.code}
											{station.note ? ` · ${station.note}` : ""}
										</span>
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
