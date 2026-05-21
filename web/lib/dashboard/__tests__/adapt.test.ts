import { describe, expect, it } from "vitest";

import type { Disruption } from "@/lib/api/disruptions-recent";
import type { LineStatus } from "@/lib/api/status-live";
import {
	disruptionForLine,
	disruptionsToNews,
	disruptionToSnapshot,
	lineStatusesToSummaries,
	lineSummaryToFallbackSnapshot,
	severityToBucket,
	summarizeCounts,
} from "@/lib/dashboard/adapt";

const SAMPLE_LINES: LineStatus[] = [
	{
		line_id: "victoria",
		line_name: "Victoria",
		mode: "tube",
		status_severity: 10,
		status_severity_description: "Good Service",
		reason: null,
		valid_from: "2026-05-13T05:00:00Z",
		valid_to: "2026-05-13T23:59:00Z",
	},
	{
		line_id: "elizabeth",
		line_name: "Elizabeth line",
		mode: "elizabeth-line",
		status_severity: 6,
		status_severity_description: "Severe Delays",
		reason: null,
		valid_from: "2026-05-13T05:00:00Z",
		valid_to: "2026-05-13T23:59:00Z",
	},
];

describe("severityToBucket", () => {
	it("maps every observed severity to one of the four buckets", () => {
		expect(severityToBucket(10)).toBe("good");
		expect(severityToBucket(20)).toBe("good");
		expect(severityToBucket(9)).toBe("minor");
		expect(severityToBucket(7)).toBe("minor");
		expect(severityToBucket(6)).toBe("severe");
		expect(severityToBucket(4)).toBe("severe");
		expect(severityToBucket(1)).toBe("suspended");
		expect(severityToBucket(0)).toBe("suspended");
	});
});

describe("lineStatusesToSummaries", () => {
	it("joins backend ids with the dashboard registry", () => {
		const [victoria, elizabeth] = lineStatusesToSummaries(SAMPLE_LINES);

		expect(victoria).toMatchObject({
			code: "VIC",
			name: "Victoria",
			color: "#039BE5",
			status: "good",
			statusText: "Good Service",
		});
		expect(elizabeth).toMatchObject({
			code: "ELZ",
			name: "Elizabeth",
			color: "#6950A1",
			status: "severe",
		});
	});

	it("threads reason + validFromIso onto the summary so the LineDetail fallback can use them", () => {
		const [, elizabeth] = lineStatusesToSummaries([
			SAMPLE_LINES[0],
			{
				...SAMPLE_LINES[1],
				reason: "Elizabeth line: signal failure at Hayes & Harlington.",
				valid_from: "2026-05-13T17:42:00Z",
			},
		]);
		expect(elizabeth.reason).toBe(
			"Elizabeth line: signal failure at Hayes & Harlington.",
		);
		expect(elizabeth.validFromIso).toBe("2026-05-13T17:42:00Z");
	});

	it("normalises a missing reason to null so consumers can branch on truthy text", () => {
		const [victoria] = lineStatusesToSummaries(SAMPLE_LINES);
		expect(victoria.reason).toBeNull();
	});

	it("coerces whitespace-only reason to null so consumers cannot trip on a truthy blank string", () => {
		const [, elizabeth] = lineStatusesToSummaries([
			SAMPLE_LINES[0],
			{ ...SAMPLE_LINES[1], reason: "   \n\t  " },
		]);
		expect(elizabeth.reason).toBeNull();
	});

	it("strips trailing ' line' so downstream components don't duplicate it", () => {
		const summaries = lineStatusesToSummaries([
			{
				...SAMPLE_LINES[0],
				line_id: "elizabeth",
				line_name: "Elizabeth line",
			},
			{
				...SAMPLE_LINES[0],
				line_id: "waterloo-city",
				line_name: "Waterloo & City",
			},
		]);
		expect(summaries[0].name).toBe("Elizabeth");
		expect(summaries[1].name).toBe("Waterloo & City");
	});

	it("prefixes unknown line ids so unrelated rows don't collide on a shared fallback code", () => {
		const summaries = lineStatusesToSummaries([
			{
				...SAMPLE_LINES[0],
				line_id: "totally-new-line",
				line_name: "Mystery",
			},
			{
				...SAMPLE_LINES[0],
				line_id: "another-new-line",
				line_name: "Other",
			},
		]);
		expect(summaries[0]).toMatchObject({
			code: "UNK:totally-new-line",
			color: "#5A6A77",
		});
		expect(summaries[1]).toMatchObject({
			code: "UNK:another-new-line",
			color: "#5A6A77",
		});
		expect(summaries[0].code).not.toBe(summaries[1].code);
	});

	it("resolves disruptions for unknown lines via the UNK: prefix", () => {
		const summaries = lineStatusesToSummaries([
			{
				...SAMPLE_LINES[0],
				line_id: "mystery-line",
				line_name: "Mystery",
			},
		]);
		const disruption: Disruption = {
			disruption_id: "MYST-001",
			category: "RealTime",
			category_description: "Real Time",
			description: "Mystery delays",
			summary: "Mystery delays",
			affected_routes: ["mystery-line"],
			affected_stops: [],
			closure_text: "",
			severity: 6,
			created: "2026-05-13T16:58:00Z",
			last_update: "2026-05-13T17:42:00Z",
		};
		expect(disruptionForLine([disruption], summaries[0])).toBe(disruption);
	});
});

describe("summarizeCounts", () => {
	it("aggregates per-bucket totals", () => {
		const summaries = lineStatusesToSummaries(SAMPLE_LINES);
		expect(summarizeCounts(summaries)).toEqual({
			good: 1,
			minor: 0,
			severe: 1,
			suspended: 0,
		});
	});
});

describe("disruptionForLine + disruptionToSnapshot", () => {
	const disruption: Disruption = {
		disruption_id: "test-1",
		category: "RealTime",
		category_description: "Real Time",
		description: "Para 1.\n\nPara 2.",
		summary: "Severe delays westbound",
		affected_routes: ["elizabeth"],
		affected_stops: ["940GZZLUHBN"],
		closure_text: "",
		severity: 6,
		created: "2026-05-13T16:58:00Z",
		last_update: "2026-05-13T17:42:00Z",
	};

	it("resolves selected line via canonical id", () => {
		const [, elizabeth] = lineStatusesToSummaries(SAMPLE_LINES);
		expect(disruptionForLine([disruption], elizabeth)).toBe(disruption);
		const [victoria] = lineStatusesToSummaries(SAMPLE_LINES);
		expect(disruptionForLine([disruption], victoria)).toBeUndefined();
	});

	it("projects backend payload onto the snapshot view-model", () => {
		const snapshot = disruptionToSnapshot(disruption);
		expect(snapshot.headline).toBe("Severe delays westbound");
		expect(snapshot.body).toEqual(["Para 1.", "Para 2."]);
		expect(snapshot.stations).toEqual([
			{ name: "940GZZLUHBN", code: "940GZZLUHBN" },
		]);
		expect(snapshot.sourceLabel).toBe("Source: TfL Unified API");
		expect(snapshot.reportedAtLabel).toMatch(/\d{2}:\d{2}/);
		expect(snapshot.updatedAtLabel).toMatch(/\d{2}:\d{2}/);
	});

	it("drops the leading description paragraph when it duplicates summary so LineDetail does not echo the headline", () => {
		// Same TfL Unified API echo pattern that `disruptionsToNews`
		// already handles — the headline would otherwise render once
		// in the .summary div and again as the first <p> body paragraph.
		const echoed: Disruption = {
			...disruption,
			summary: "Piccadilly Line: SUSPENDED between Acton Town and Heathrow.",
			description:
				"Piccadilly Line: SUSPENDED between Acton Town and Heathrow.\n\nTickets accepted on London Buses.",
		};
		const snapshot = disruptionToSnapshot(echoed);
		expect(snapshot.headline).toBe(
			"Piccadilly Line: SUSPENDED between Acton Town and Heathrow.",
		);
		expect(snapshot.body).toEqual(["Tickets accepted on London Buses."]);
	});

	it("keeps the full description when the leading paragraph does not match summary", () => {
		const snapshot = disruptionToSnapshot({
			...disruption,
			summary: "Severe delays westbound",
			description: "Para 1.\n\nPara 2.\n\nPara 3.",
		});
		expect(snapshot.body).toEqual(["Para 1.", "Para 2.", "Para 3."]);
	});
});

describe("lineSummaryToFallbackSnapshot", () => {
	const baseSummary = {
		code: "PIC",
		name: "Piccadilly",
		color: "#0019A8",
		status: "suspended" as const,
		statusText: "Part Suspended",
		updatedLabel: "updated 6m ago",
	};

	it("returns undefined when the line has no reason text", () => {
		expect(lineSummaryToFallbackSnapshot(baseSummary)).toBeUndefined();
		expect(
			lineSummaryToFallbackSnapshot({ ...baseSummary, reason: null }),
		).toBeUndefined();
		expect(
			lineSummaryToFallbackSnapshot({ ...baseSummary, reason: "   " }),
		).toBeUndefined();
	});

	it("projects the status-feed reason into a DisruptionSnapshot with empty stations", () => {
		const snapshot = lineSummaryToFallbackSnapshot({
			...baseSummary,
			reason:
				"Piccadilly Line: No service between Northfields and Heathrow Airport while we fix a signal failure at Northfields.",
			validFromIso: "2026-05-19T23:36:00Z",
		});
		expect(snapshot).toBeDefined();
		if (!snapshot) return;
		expect(snapshot.headline).toBe("Part Suspended");
		expect(snapshot.body).toEqual([
			"Piccadilly Line: No service between Northfields and Heathrow Airport while we fix a signal failure at Northfields.",
		]);
		expect(snapshot.stations).toEqual([]);
		expect(snapshot.sourceLabel).toBe("Source: TfL Unified API (status feed)");
		expect(snapshot.reportedAtLabel).toMatch(/\d{2}:\d{2}/);
		expect(snapshot.updatedAtLabel).toBe(snapshot.reportedAtLabel);
	});

	it("falls back to '—' for reportedAtLabel when validFromIso is missing", () => {
		const snapshot = lineSummaryToFallbackSnapshot({
			...baseSummary,
			reason: "Something happened.",
		});
		expect(snapshot?.reportedAtLabel).toBe("—");
	});

	it("splits multi-paragraph reason text so LineDetail renders each paragraph in its own <p>", () => {
		// TfL occasionally returns reason text with explicit \n\n separators
		// — e.g. "Piccadilly Line: suspended.\n\nTickets accepted on London Buses."
		// Joining into a single array element would collapse the paragraph
		// break under HTML whitespace rules; splitting matches what
		// disruptionToSnapshot emits.
		const snapshot = lineSummaryToFallbackSnapshot({
			...baseSummary,
			reason:
				"Piccadilly Line: suspended between Acton Town and Heathrow.\n\nTickets accepted on London Buses.",
			validFromIso: "2026-05-19T23:36:00Z",
		});
		expect(snapshot?.body).toEqual([
			"Piccadilly Line: suspended between Acton Town and Heathrow.",
			"Tickets accepted on London Buses.",
		]);
	});
});

describe("disruptionsToNews", () => {
	// Fixed clock anchor 2h after the baseDisruption last_update so the
	// 12h window keeps the row by default. Individual tests override `now`
	// when they need to exercise the cutoff boundary.
	const NOW = new Date("2026-05-13T18:58:00Z");

	const baseDisruption: Disruption = {
		disruption_id: "test-news-1",
		category: "RealTime",
		category_description: "Real Time",
		description: "Faulty train at Hayes & Harlington.",
		summary: "Elizabeth line — westbound severe delays",
		affected_routes: ["elizabeth"],
		affected_stops: [],
		closure_text: "",
		severity: 6,
		created: "2026-05-13T16:30:00Z",
		last_update: "2026-05-13T16:58:00Z",
	};

	it("projects disruptions onto the news view-model in descending update order", () => {
		const earlier: Disruption = {
			...baseDisruption,
			disruption_id: "test-news-2",
			summary: "Northern line — Bank branch part-suspended",
			description: "No service between Kennington and Moorgate.",
			last_update: "2026-05-13T15:20:00Z",
		};
		const items = disruptionsToNews([earlier, baseDisruption], NOW);
		expect(items).toHaveLength(2);
		expect(items[0].title).toBe("Elizabeth line — westbound severe delays");
		expect(items[0].body).toBe("Faulty train at Hayes & Harlington.");
		expect(items[0].time).toMatch(/^\d{2}:\d{2}$/);
		expect(items[1].title).toBe("Northern line — Bank branch part-suspended");
	});

	it("drops rows whose last_update is unparseable so the 12h window stays honest", () => {
		// Pre-TM-28 we surfaced these with `time: "—"`; the new window
		// filter has to assume an unknown timestamp is outside the window,
		// otherwise a broken payload could silently extend the surface.
		const broken: Disruption = { ...baseDisruption, last_update: "not-a-date" };
		expect(disruptionsToNews([broken], NOW)).toEqual([]);
	});

	it("returns an empty list when no disruptions are supplied", () => {
		expect(disruptionsToNews([], NOW)).toEqual([]);
	});

	it("drops the leading paragraph of description when it duplicates summary so title and body do not echo", () => {
		const echoed: Disruption = {
			...baseDisruption,
			summary: "Piccadilly Line: SUSPENDED between Acton Town and Heathrow.",
			description:
				"Piccadilly Line: SUSPENDED between Acton Town and Heathrow.\n\nTickets accepted on London Buses and the Elizabeth line.",
		};
		const [item] = disruptionsToNews([echoed], NOW);
		expect(item.title).toBe(
			"Piccadilly Line: SUSPENDED between Acton Town and Heathrow.",
		);
		expect(item.body).toBe(
			"Tickets accepted on London Buses and the Elizabeth line.",
		);
	});

	it("returns an empty body when the description only echoes summary", () => {
		const onlyEcho: Disruption = {
			...baseDisruption,
			summary: "Circle Line: Minor delays due to train cancellations.",
			description: "Circle Line: Minor delays due to train cancellations.",
		};
		const [item] = disruptionsToNews([onlyEcho], NOW);
		expect(item.body).toBe("");
	});

	it("joins trailing paragraphs with a blank line so multi-paragraph context is preserved", () => {
		const verbose: Disruption = {
			...baseDisruption,
			summary: "Piccadilly Line: SUSPENDED between Acton Town and Heathrow.",
			description:
				"Piccadilly Line: SUSPENDED between Acton Town and Heathrow.\n\nTickets accepted on London Buses.\n\nLast updated 18:42.",
		};
		const [item] = disruptionsToNews([verbose], NOW);
		expect(item.body).toBe(
			"Tickets accepted on London Buses.\n\nLast updated 18:42.",
		);
	});

	it("keeps the full description when the leading paragraph does not match summary", () => {
		const distinct: Disruption = {
			...baseDisruption,
			summary: "Elizabeth line — westbound severe delays",
			description:
				"Faulty train at Hayes & Harlington.\n\nTickets accepted on Piccadilly & Bakerloo until service is restored.",
		};
		const [item] = disruptionsToNews([distinct], NOW);
		expect(item.body).toBe(
			"Faulty train at Hayes & Harlington.\n\nTickets accepted on Piccadilly & Bakerloo until service is restored.",
		);
	});

	it("keeps line-broken sentences together within a single paragraph", () => {
		// Real TfL payloads sometimes inject a single `\n` between sentences
		// inside the same paragraph; splitting on it would clip the body
		// mid-thought. We only split on blank lines.
		const wrapped: Disruption = {
			...baseDisruption,
			description: "Train at Hayes & Harlington.\nAlternatives: take the bus.",
		};
		const [item] = disruptionsToNews([wrapped], NOW);
		expect(item.body).toBe(
			"Train at Hayes & Harlington.\nAlternatives: take the bus.",
		);
	});

	it("handles CRLF blank lines so Windows-encoded payloads strip the echoed lead too", () => {
		const crlf: Disruption = {
			...baseDisruption,
			summary: "Piccadilly Line: SUSPENDED between Acton Town and Heathrow.",
			description:
				"Piccadilly Line: SUSPENDED between Acton Town and Heathrow.\r\n\r\nTickets accepted on London Buses.",
		};
		const [item] = disruptionsToNews([crlf], NOW);
		expect(item.body).toBe("Tickets accepted on London Buses.");
	});

	it("drops rows whose last_update is older than 12 hours so the news list stays current", () => {
		// Ingestion replays the entire /Disruption payload every cycle, so
		// stale rows linger in the DB long after TfL has cleared them on
		// the live status feed. The news pane is a "what's happening now"
		// surface, so we cap visibility at 12 h.
		const stale: Disruption = {
			...baseDisruption,
			disruption_id: "stale",
			last_update: "2026-05-13T06:57:00Z", // 12h 1m before NOW
		};
		const fresh: Disruption = {
			...baseDisruption,
			disruption_id: "fresh",
			summary: "Northern line — Bank branch part-suspended",
			last_update: "2026-05-13T18:30:00Z", // 28m before NOW
		};
		const items = disruptionsToNews([stale, fresh], NOW);
		expect(items).toHaveLength(1);
		expect(items[0].title).toBe("Northern line — Bank branch part-suspended");
	});

	it("keeps a row exactly 12 hours old so the window cutoff is inclusive at the boundary", () => {
		// Avoids losing legitimate ongoing incidents to clock drift between
		// the consumer's `last_update` write and the browser's `now`.
		const boundary: Disruption = {
			...baseDisruption,
			last_update: "2026-05-13T06:58:00Z", // exactly 12h before NOW
		};
		expect(disruptionsToNews([boundary], NOW)).toHaveLength(1);
	});

	it("collapses content-exact duplicates keeping the most recent occurrence", () => {
		// TfL re-publishes the same disruption on every poll (currently 5 min)
		// with a refreshed `last_update`. Without dedup the news pane fills
		// with N copies of the same Mildmay / Piccadilly closure within an
		// hour. We dedup on the rendered content (title + body) rather than
		// `disruption_id` because TfL sometimes re-issues a closure under a
		// new id with identical text.
		const mildmayLater: Disruption = {
			...baseDisruption,
			disruption_id: "mildmay-3",
			summary: "Mildmay line: Part suspended between Highbury and Stratford.",
			description:
				"Mildmay line: Part suspended between Highbury and Stratford.",
			last_update: "2026-05-13T18:55:00Z",
		};
		const mildmayMid: Disruption = {
			...baseDisruption,
			disruption_id: "mildmay-2",
			summary: "Mildmay line: Part suspended between Highbury and Stratford.",
			description:
				"Mildmay line: Part suspended between Highbury and Stratford.",
			last_update: "2026-05-13T18:50:00Z",
		};
		const mildmayEarliest: Disruption = {
			...baseDisruption,
			disruption_id: "mildmay-1",
			summary: "Mildmay line: Part suspended between Highbury and Stratford.",
			description:
				"Mildmay line: Part suspended between Highbury and Stratford.",
			last_update: "2026-05-13T18:45:00Z",
		};

		const items = disruptionsToNews(
			[mildmayEarliest, mildmayMid, mildmayLater],
			NOW,
		);
		expect(items).toHaveLength(1);
		// London-local for 18:55 UTC on 2026-05-13 (BST = UTC+1).
		expect(items[0].time).toBe("19:55");
	});

	it("keeps distinct disruptions even when one repeats — image-4 fixture: 3× Mildmay + 3× Piccadilly → 2 rows", () => {
		const mk = (
			id: string,
			summary: string,
			lastUpdate: string,
		): Disruption => ({
			...baseDisruption,
			disruption_id: id,
			summary,
			description: summary,
			last_update: lastUpdate,
		});
		const items = disruptionsToNews(
			[
				mk("mil-1", "Mildmay line: Part suspended.", "2026-05-13T18:40:00Z"),
				mk("mil-2", "Mildmay line: Part suspended.", "2026-05-13T18:45:00Z"),
				mk("mil-3", "Mildmay line: Part suspended.", "2026-05-13T18:50:00Z"),
				mk("pic-1", "Piccadilly Line: SUSPENDED.", "2026-05-13T18:42:00Z"),
				mk("pic-2", "Piccadilly Line: SUSPENDED.", "2026-05-13T18:47:00Z"),
				mk("pic-3", "Piccadilly Line: SUSPENDED.", "2026-05-13T18:52:00Z"),
			],
			NOW,
		);
		expect(items.map((i) => i.title)).toEqual([
			"Piccadilly Line: SUSPENDED.",
			"Mildmay line: Part suspended.",
		]);
	});
});
