export interface PageHeadProps {
	lineCount: number;
	lastRefreshedLabel: string;
	refreshIntervalSeconds: number;
}

export function PageHead({
	lineCount,
	lastRefreshedLabel,
	refreshIntervalSeconds,
}: PageHeadProps) {
	return (
		<header className="tfl-pageh">
			<h1>London transport — at a glance</h1>
			<span className="meta">
				{lineCount} lines · last refreshed {lastRefreshedLabel} · auto-refresh
				every {refreshIntervalSeconds}s
			</span>
		</header>
	);
}
