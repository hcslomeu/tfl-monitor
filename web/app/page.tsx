"use client";

import { useEffect, useMemo, useState } from "react";

import { BusBanner } from "@/components/dashboard/bus-banner";
import { ChatPanel } from "@/components/dashboard/chat-panel";
import { LineDetail } from "@/components/dashboard/line-detail";
import { LineGrid } from "@/components/dashboard/line-grid";
import { NewsReports } from "@/components/dashboard/news-reports";
import { TopNav } from "@/components/dashboard/top-nav";
import { WorkInProgress } from "@/components/work-in-progress";
import { getRecentDisruptions } from "@/lib/api/disruptions-recent";
import { getStatusLive } from "@/lib/api/status-live";
import {
	disruptionForLine,
	disruptionsToNews,
	disruptionToSnapshot,
	lineStatusesToSummaries,
	lineSummaryToFallbackSnapshot,
	summarizeCounts,
} from "@/lib/dashboard/adapt";
import { useAutoRefresh } from "@/lib/hooks/use-auto-refresh";
import { useMediaQuery } from "@/lib/hooks/use-media-query";
import { MOCK_BUSES } from "@/lib/mocks/buses";

const REFRESH_INTERVAL_MS = 30_000;
const REPO_URL = "https://github.com/humbertolomeu/tfl-monitor";
// Mirrors the `@media (max-width: 880px)` stacking breakpoint: below it the
// line detail renders inline (accordion); above it, in the right column.
const STACK_QUERY = "(max-width: 880px)";

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
		if (!selectedLine) return undefined;
		if (disruptions.data) {
			const match = disruptionForLine(disruptions.data, selectedLine);
			if (match) return disruptionToSnapshot(match);
		}
		return lineSummaryToFallbackSnapshot(selectedLine);
	}, [disruptions.data, selectedLine]);

	const newsItems = useMemo(
		() => (disruptions.data ? disruptionsToNews(disruptions.data) : []),
		[disruptions.data],
	);

	const clockLabel = formatLondonClock(status.lastUpdated);

	const isStacked = useMediaQuery(STACK_QUERY);
	// Mobile accordion can be collapsed; desktop's right column always shows the
	// detail, so `expanded` only takes effect when stacked.
	const [expanded, setExpanded] = useState(true);

	const handleSelect = (code: string) => {
		if (code === selectedCode) {
			setExpanded((open) => !open);
		} else {
			setSelectedCode(code);
			setExpanded(true);
		}
	};

	const inlineOpen = isStacked && expanded;
	const rowActive = !isStacked || expanded;

	const lineDetail = selectedLine ? (
		<LineDetail line={selectedLine} disruption={selectedDisruption} />
	) : null;

	return (
		<div className="tfl-app">
			<TopNav summary={counts} clockLabel={clockLabel} repoUrl={REPO_URL} />
			<main className="tfl-shell">
				<section className="tfl-grid">
					<LineGrid
						lines={lineSummaries}
						selected={rowActive ? (selectedCode ?? undefined) : undefined}
						onSelect={handleSelect}
						detail={inlineOpen ? lineDetail : null}
						onCloseDetail={() => setExpanded(false)}
					/>
					<div className="tfl-right-col">
						{isStacked ? null : lineDetail}
						<ChatPanel />
					</div>
				</section>
				<section className="tfl-news-band">
					<NewsReports items={newsItems} />
				</section>
				<section className="tfl-bus-band">
					<BusBanner buses={MOCK_BUSES} />
				</section>
			</main>
			<WorkInProgress
				label="TfL Monitor — still being built"
				storageKey="tflm-wip-dismissed"
				anchorSelector=".tfl-nav"
			/>
		</div>
	);
}
