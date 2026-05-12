import type { NewsItem } from "./types";

export interface NewsReportsProps {
	items: NewsItem[];
	slotCount?: number;
}

export function NewsReports({ items, slotCount = 3 }: NewsReportsProps) {
	const filled = items.slice(0, slotCount);
	const empties = Math.max(0, slotCount - filled.length);
	const slots: (NewsItem | null)[] = [
		...filled,
		...Array.from({ length: empties }, () => null),
	];

	return (
		<section className="tfl-card tfl-news">
			<div className="tfl-card-h">
				<h4>News &amp; reports from TfL</h4>
				<span className="meta">{filled.length} today</span>
			</div>
			<ul className="tfl-news-list">
				{slots.map((slot, index) => {
					const key = slot ? `${slot.time}-${slot.title}` : `empty-${index}`;
					return (
						<li key={key} className={slot ? "" : "is-empty"}>
							<span className="tfl-news-time">{slot ? slot.time : ""}</span>
							<div>
								{slot ? (
									<>
										<div className="tfl-news-title">{slot.title}</div>
										<div className="tfl-news-body">{slot.body}</div>
									</>
								) : (
									<div className="tfl-news-placeholder">No further updates</div>
								)}
							</div>
						</li>
					);
				})}
			</ul>
		</section>
	);
}
