"use client";

import { useMemo } from "react";

import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import type { Disruption } from "@/lib/api/disruptions-recent";

interface ComingUpCardProps {
	disruptions: Disruption[];
}

const MAX_ITEMS = 5;
const DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
	day: "2-digit",
	month: "short",
	timeZone: "Europe/London",
});

function formatStart(iso: string): string {
	return DATE_FORMATTER.format(new Date(iso));
}

export function ComingUpCard({ disruptions }: ComingUpCardProps) {
	const upcoming = useMemo(() => {
		return disruptions
			.filter((d) => d.category === "PlannedWork")
			.sort(
				(a, b) => new Date(a.created).getTime() - new Date(b.created).getTime(),
			)
			.slice(0, MAX_ITEMS);
	}, [disruptions]);

	return (
		<Card>
			<CardHeader>
				<CardTitle>📅 Coming up</CardTitle>
				<CardDescription>Planned work · upcoming</CardDescription>
			</CardHeader>
			<CardContent>
				{upcoming.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						No planned work scheduled.
					</p>
				) : (
					<ul
						className="flex flex-col gap-2"
						aria-label="Upcoming planned work"
					>
						{upcoming.map((d) => (
							<li
								key={`${d.disruption_id}-${d.created}`}
								className="rounded border-l-4 border-indigo-500 bg-indigo-50 p-2 dark:bg-indigo-950/30"
							>
								<div className="text-sm font-semibold">
									{formatStart(d.created)} · {d.summary}
								</div>
								{d.description ? (
									<p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
										{d.description}
									</p>
								) : null}
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
