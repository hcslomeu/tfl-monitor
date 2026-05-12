"use client";

import { useMemo } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import type { Disruption } from "@/lib/api/disruptions-recent";

interface HappeningNowCardProps {
	disruptions: Disruption[];
}

const ACTIVE_CATEGORIES: ReadonlySet<Disruption["category"]> = new Set([
	"RealTime",
	"Incident",
]);

export function HappeningNowCard({ disruptions }: HappeningNowCardProps) {
	const active = useMemo(() => {
		return disruptions
			.filter((d) => ACTIVE_CATEGORIES.has(d.category))
			.sort(
				(a, b) =>
					new Date(b.last_update).getTime() - new Date(a.last_update).getTime(),
			);
	}, [disruptions]);

	return (
		<Card>
			<CardHeader>
				<CardTitle>⚠ Happening now</CardTitle>
				<CardDescription>RealTime · Incident</CardDescription>
			</CardHeader>
			<CardContent>
				{active.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						✅ All clear across the network.
					</p>
				) : (
					<ul className="flex flex-col gap-2" aria-label="Active disruptions">
						{active.map((d) => (
							<li
								key={`${d.disruption_id}-${d.last_update}`}
								className="rounded border-l-4 border-red-600 bg-red-50 p-2 dark:bg-red-950/30"
							>
								<div className="text-sm font-semibold">{d.summary}</div>
								{d.description ? (
									<p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
										{d.description}
									</p>
								) : null}
								{d.affected_routes.length > 0 ? (
									<ul
										className="mt-2 flex flex-wrap gap-1"
										aria-label="Affected routes"
									>
										{d.affected_routes.map((r) => (
											<li key={r}>
												<Badge variant="outline">{r}</Badge>
											</li>
										))}
									</ul>
								) : null}
								{d.closure_text ? (
									<Alert variant="destructive" className="mt-2">
										<AlertDescription>{d.closure_text}</AlertDescription>
									</Alert>
								) : null}
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
