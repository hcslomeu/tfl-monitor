import type { NewsItem } from "./types";

export interface NewsReportsProps {
	items: NewsItem[];
}

export function NewsReports({ items }: NewsReportsProps) {
	return (
		<section className="tfl-card tfl-news">
			<div className="tfl-card-h">
				<h4>News &amp; reports from TfL</h4>
				<span className="meta">{items.length} in last 12h</span>
			</div>
			<ul className="tfl-news-list">
				{items.length === 0 ? (
					<li className="is-empty">
						<span className="tfl-news-time" />
						<div>
							<div className="tfl-news-placeholder">No recent updates</div>
						</div>
					</li>
				) : (
					items.map((item) => (
						<li key={`${item.time}-${item.title}-${item.body}`}>
							<span className="tfl-news-time">{item.time}</span>
							<div>
								<div className="tfl-news-title">{item.title}</div>
								{item.body ? (
									<div className="tfl-news-body">{item.body}</div>
								) : null}
							</div>
						</li>
					))
				)}
			</ul>
		</section>
	);
}
