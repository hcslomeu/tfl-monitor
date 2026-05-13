import type { BusItem } from "./types";

export interface BusBannerProps {
	buses: BusItem[];
}

export function BusBanner({ buses }: BusBannerProps) {
	return (
		<section className="tfl-card tfl-bus">
			<div className="tfl-card-h">
				<h4>Buses worth knowing about</h4>
				<span className="meta">{buses.length} routes flagged</span>
			</div>
			<div className="tfl-bus-row">
				{buses.map((bus) => (
					<div key={bus.route} className="tfl-bus-cell">
						<span className="tfl-bus-route">{bus.route}</span>
						<span className="tfl-bus-text">{bus.text}</span>
					</div>
				))}
			</div>
		</section>
	);
}
