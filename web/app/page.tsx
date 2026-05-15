"use client";

import { useEffect, useMemo, useState } from "react";

import { BusBanner } from "@/components/dashboard/bus-banner";
import { ChatPanel } from "@/components/dashboard/chat-panel";
import { LineDetail } from "@/components/dashboard/line-detail";
import { LineGrid } from "@/components/dashboard/line-grid";
import { NewsReports } from "@/components/dashboard/news-reports";
import { TopNav } from "@/components/dashboard/top-nav";
import { getRecentDisruptions } from "@/lib/api/disruptions-recent";
import { getStatusLive } from "@/lib/api/status-live";
import {
	disruptionForLine,
	disruptionToSnapshot,
	lineStatusesToSummaries,
	summarizeCounts,
} from "@/lib/dashboard/adapt";
import { useAutoRefresh } from "@/lib/hooks/use-auto-refresh";
import { MOCK_BUSES } from "@/lib/mocks/buses";
import { MOCK_NEWS } from "@/lib/mocks/news";

const REFRESH_INTERVAL_MS = 30_000;
const REPO_URL = "https://github.com/humbertolomeu/tfl-monitor";

function formatLondonClock(date: Date | null): string {
	if (!date) return "—";
	const time = date.toLocaleTimeString("en-GB", {
		hour: "2-digit",
		minute: "2-digit",
		timeZone: "Europe/London",
		timeZoneName: "short",
	});
	return `${time} · live`;
}

export default function HomePage() {
	const status = useAutoRefresh(getStatusLive, REFRESH_INTERVAL_MS);
	const disruptions = useAutoRefresh(getRecentDisruptions, REFRESH_INTERVAL_MS);

	const lineSummaries = useMemo(
		() => (status.data ? lineStatusesToSummaries(status.data) : []),
		[status.data],
	);
	const counts = useMemo(() => summarizeCounts(lineSummaries), [lineSummaries]);

	const [selectedCode, setSelectedCode] = useState<string | null>(null);

	useEffect(() => {
		if (lineSummaries.length === 0) return;
		if (
			selectedCode &&
			lineSummaries.some((line) => line.code === selectedCode)
		) {
			return;
		}
		const preferred =
			lineSummaries.find((line) => line.status === "severe") ??
			lineSummaries[0];
		setSelectedCode(preferred.code);
	}, [selectedCode, lineSummaries]);

	const selectedLine = useMemo(
		() => lineSummaries.find((line) => line.code === selectedCode) ?? null,
		[lineSummaries, selectedCode],
	);

	const selectedDisruption = useMemo(() => {
		if (!selectedLine || !disruptions.data) return undefined;
		const match = disruptionForLine(disruptions.data, selectedLine);
		return match ? disruptionToSnapshot(match) : undefined;
	}, [disruptions.data, selectedLine]);

	const clockLabel = formatLondonClock(status.lastUpdated);

	return (
		<div className="tfl-app">
			<TopNav summary={counts} clockLabel={clockLabel} repoUrl={REPO_URL} />
			<main className="tfl-grid">
				<div className="tfl-left-col">
					<LineGrid
						lines={lineSummaries}
						selected={selectedCode ?? undefined}
						onSelect={setSelectedCode}
					/>
					<div className="tfl-left-bottom">
						<BusBanner buses={MOCK_BUSES} />
						<NewsReports items={MOCK_NEWS} />
					</div>
				</div>
				<div className="tfl-right-col">
					{selectedLine ? (
						<LineDetail line={selectedLine} disruption={selectedDisruption} />
					) : null}
					<ChatPanel />
				</div>
			</main>
		</div>
	);
}
