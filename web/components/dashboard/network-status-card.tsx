"use client";

import { useEffect, useMemo, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { LineStatus } from "@/lib/api/status-live";
import { modeLabel } from "@/lib/labels";

const STORAGE_KEY = "tfl-monitor:last-mode";

interface NetworkStatusCardProps {
	lines: LineStatus[];
	lastUpdated: Date | null;
}

type TabId =
	| "tube"
	| "elizabeth-line"
	| "overground"
	| "dlr"
	| "tram-river-cable"
	| "bus";

const TAB_ORDER: { id: TabId; label: string; modes: LineStatus["mode"][] }[] = [
	{ id: "tube", label: "Tube", modes: ["tube"] },
	{ id: "elizabeth-line", label: "Elizabeth line", modes: ["elizabeth-line"] },
	{ id: "overground", label: "Overground", modes: ["overground"] },
	{ id: "dlr", label: "DLR", modes: ["dlr"] },
	{
		id: "tram-river-cable",
		label: "Tram · River · Cable",
		modes: ["tram", "river-bus", "cable-car", "national-rail"],
	},
	{ id: "bus", label: "Bus", modes: ["bus"] },
];

const VALID_TABS = new Set<TabId>(TAB_ORDER.map((t) => t.id));

function readStoredTab(): TabId {
	if (typeof window === "undefined") return "tube";
	const stored = window.localStorage.getItem(STORAGE_KEY);
	return stored && VALID_TABS.has(stored as TabId) ? (stored as TabId) : "tube";
}

const RELATIVE_FORMATTER = new Intl.RelativeTimeFormat("en", {
	numeric: "auto",
});

function formatLastUpdated(d: Date | null): string {
	if (!d) return "never";
	const seconds = Math.round((d.getTime() - Date.now()) / 1000);
	return RELATIVE_FORMATTER.format(seconds, "second");
}

function useTicker(intervalMs: number): void {
	const [, setTick] = useState(0);
	useEffect(() => {
		const id = setInterval(() => setTick((n) => n + 1), intervalMs);
		return () => clearInterval(id);
	}, [intervalMs]);
}

export function NetworkStatusCard({
	lines,
	lastUpdated,
}: NetworkStatusCardProps) {
	const [tab, setTab] = useState<TabId>("tube");

	useEffect(() => {
		setTab(readStoredTab());
	}, []);

	useTicker(1_000);

	const active = useMemo(
		() => TAB_ORDER.find((t) => t.id === tab) ?? TAB_ORDER[0],
		[tab],
	);
	const filtered = useMemo(
		() => lines.filter((l) => active.modes.includes(l.mode)),
		[lines, active],
	);

	function changeTab(next: string) {
		const id = next as TabId;
		if (!VALID_TABS.has(id)) return;
		setTab(id);
		try {
			window.localStorage.setItem(STORAGE_KEY, id);
		} catch {
			// localStorage may be unavailable in private mode; non-fatal.
		}
	}

	const listLabel = `${active.label} lines`;

	return (
		<Card>
			<CardHeader>
				<CardTitle>Network status</CardTitle>
				<CardDescription>
					Updated {formatLastUpdated(lastUpdated)} · auto-refresh 30 s
				</CardDescription>
			</CardHeader>
			<CardContent>
				<Tabs value={tab} onValueChange={changeTab}>
					<TabsList className="mb-3">
						{TAB_ORDER.map((t) => (
							<TabsTrigger key={t.id} value={t.id}>
								{t.label}
							</TabsTrigger>
						))}
					</TabsList>
				</Tabs>

				{filtered.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						No lines reported for {active.label}.
					</p>
				) : (
					<ul
						aria-label={listLabel}
						className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3"
					>
						{filtered.map((line) => (
							<li
								key={line.line_id}
								className="rounded border-l-4 border-emerald-600 bg-card p-2"
								data-testid={`line-${line.line_id}`}
							>
								<div className="flex items-baseline justify-between gap-2">
									<span className="text-sm font-semibold">
										{line.line_name}
									</span>
									<span className="text-[10px] text-muted-foreground">
										{modeLabel(line.mode)}
									</span>
								</div>
								<div className="mt-1">
									<StatusBadge
										severity={line.status_severity}
										description={line.status_severity_description}
									/>
								</div>
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
