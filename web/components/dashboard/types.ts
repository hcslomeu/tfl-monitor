/**
 * Shared shapes consumed by dashboard components.
 *
 * The shapes intentionally diverge from the auto-generated OpenAPI types
 * in `web/lib/types.ts`: components consume a denormalised view-model
 * (status bucket + display colour) rather than the raw backend payload,
 * so the same components can be hydrated by mocks or by a real fetcher
 * adapter without leaking server-side concerns.
 */

export type StatusBucket = "good" | "minor" | "severe" | "suspended";

export interface LineSummary {
	code: string;
	name: string;
	color: string;
	status: StatusBucket;
	statusText: string;
	updatedLabel: string;
}

export interface StatusSummaryCounts {
	good: number;
	minor: number;
	severe: number;
	suspended: number;
}

export interface DisruptionStation {
	name: string;
	code: string;
	note?: string;
}

export interface DisruptionSnapshot {
	headline: string;
	body: string[];
	reportedAtLabel: string;
	stations: DisruptionStation[];
	sourceLabel: string;
	updatedAtLabel: string;
}

export interface BusItem {
	route: string;
	text: string;
}

export interface NewsItem {
	time: string;
	title: string;
	body: string;
}

export interface ChatMessage {
	who: "user" | "bot";
	text: string;
}
