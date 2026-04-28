/**
 * Disruption Log — recent disruptions across the served network.
 *
 * Reads from the FastAPI `/api/v1/disruptions/recent` handler via
 * `getRecentDisruptions()`. `apiFetch` surfaces non-2xx responses as
 * `ApiError`, which the page catches to render a fallback alert.
 */

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	type Disruption,
	getRecentDisruptions,
} from "@/lib/api/disruptions-recent";
import { ApiError } from "@/lib/api-client";

const UPDATED_FORMATTER = new Intl.DateTimeFormat("en-GB", {
	day: "2-digit",
	month: "short",
	hour: "2-digit",
	minute: "2-digit",
	timeZone: "Europe/London",
});

function formatUpdated(value: string): string {
	return UPDATED_FORMATTER.format(new Date(value));
}

const CATEGORY_LABELS: Record<Disruption["category"], string> = {
	RealTime: "Real Time",
	PlannedWork: "Planned Work",
	Information: "Information",
	Incident: "Incident",
	Undefined: "Other",
};

type CategoryTone = "severe" | "minor" | "info" | "neutral";

function categoryTone(category: Disruption["category"]): CategoryTone {
	if (category === "RealTime" || category === "Incident") return "severe";
	if (category === "PlannedWork") return "minor";
	if (category === "Information") return "info";
	return "neutral";
}

function CategoryBadge({ category }: { category: Disruption["category"] }) {
	const tone = categoryTone(category);
	const label = CATEGORY_LABELS[category];

	if (tone === "severe") {
		return (
			<Badge variant="destructive" data-tone="severe">
				{label}
			</Badge>
		);
	}
	if (tone === "minor") {
		return (
			<Badge
				variant="secondary"
				data-tone="minor"
				className="bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200"
			>
				{label}
			</Badge>
		);
	}
	if (tone === "info") {
		return (
			<Badge
				variant="secondary"
				data-tone="info"
				className="bg-sky-100 text-sky-900 dark:bg-sky-500/20 dark:text-sky-200"
			>
				{label}
			</Badge>
		);
	}
	return (
		<Badge variant="outline" data-tone="neutral">
			{label}
		</Badge>
	);
}

export default async function DisruptionsPage() {
	let disruptions: Disruption[] | null = null;
	let errorDetail: string | null = null;

	try {
		disruptions = await getRecentDisruptions();
	} catch (err) {
		if (err instanceof ApiError) {
			errorDetail = err.detail;
		} else {
			errorDetail = err instanceof Error ? err.message : "Unknown error";
		}
	}

	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-12">
			<header className="flex flex-col gap-1">
				<h1 className="font-heading text-2xl font-semibold tracking-tight">
					Disruption Log
				</h1>
				<p className="text-sm text-muted-foreground">
					Recent disruptions across the served TfL lines, ordered by latest
					update.
				</p>
			</header>

			{errorDetail ? (
				<Alert role="alert">
					<AlertTitle>Disruptions unavailable</AlertTitle>
					<AlertDescription>{errorDetail}</AlertDescription>
				</Alert>
			) : disruptions && disruptions.length === 0 ? (
				<Alert>
					<AlertTitle>No disruptions reported</AlertTitle>
					<AlertDescription>
						The API returned no disruption rows for the served network.
					</AlertDescription>
				</Alert>
			) : (
				<section
					aria-label="Recent disruptions"
					className="flex flex-col gap-3"
					data-testid="disruption-list"
				>
					{(disruptions ?? []).map((d) => (
						<Card key={d.disruption_id}>
							<CardHeader>
								<CardTitle className="flex flex-wrap items-center gap-2">
									<span>{d.summary}</span>
									<CategoryBadge category={d.category} />
								</CardTitle>
								<CardDescription className="flex flex-wrap items-center gap-2">
									<span>Updated {formatUpdated(d.last_update)}</span>
									{d.affected_routes.length > 0 ? (
										<>
											<span aria-hidden>·</span>
											<ul
												aria-label="Affected routes"
												className="flex flex-wrap gap-1"
											>
												{d.affected_routes.map((route) => (
													<li key={route}>
														<Badge variant="outline">{route}</Badge>
													</li>
												))}
											</ul>
										</>
									) : null}
								</CardDescription>
							</CardHeader>
							<CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
								<p>{d.description}</p>
								{d.closure_text ? (
									<Alert variant="destructive">
										<AlertTitle>Closure</AlertTitle>
										<AlertDescription>{d.closure_text}</AlertDescription>
									</Alert>
								) : null}
							</CardContent>
						</Card>
					))}
				</section>
			)}
		</main>
	);
}
