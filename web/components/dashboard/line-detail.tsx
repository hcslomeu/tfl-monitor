import type { DisruptionSnapshot, LineSummary } from "./types";

export interface LineDetailProps {
	line: LineSummary;
	disruption?: DisruptionSnapshot;
}

export function LineDetail({ line, disruption }: LineDetailProps) {
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
						{line.code} · {line.statusText}
						{disruption ? ` · reported ${disruption.reportedAtLabel}` : ""}
					</div>
				</div>
			</div>
			{disruption ? (
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
					<p>No active disruption reported for this line.</p>
				</div>
			)}
		</section>
	);
}
