/**
 * Network Now — landing view.
 *
 * Reads live operational status from the FastAPI `/status/live`
 * handler via `getStatusLive()`. TM-E1b wires the real call;
 * `apiFetch` surfaces non-2xx responses as `ApiError`, which the
 * page catches to render a fallback alert.
 */

import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { getStatusLive, type LineStatus } from "@/lib/api/status-live";

const VALIDITY_FORMATTER = new Intl.DateTimeFormat("en-GB", {
	hour: "2-digit",
	minute: "2-digit",
	timeZone: "Europe/London",
});

function formatWindow(line: LineStatus): string {
	const from = VALIDITY_FORMATTER.format(new Date(line.valid_from));
	const to = VALIDITY_FORMATTER.format(new Date(line.valid_to));
	return `${from}–${to}`;
}

/**
 * TfL brand-correct labels for each transport mode.
 *
 * The OpenAPI enum is kebab-case (`elizabeth-line`, `national-rail`, …);
 * blindly replacing hyphens and using Tailwind `capitalize` produces
 * `Elizabeth line` and `National rail`, which both miss the brand.
 */
const MODE_LABELS: Record<LineStatus["mode"], string> = {
	tube: "Tube",
	"elizabeth-line": "Elizabeth Line",
	overground: "Overground",
	dlr: "DLR",
	bus: "Bus",
	"national-rail": "National Rail",
	"river-bus": "River Bus",
	"cable-car": "Cable Car",
	tram: "Tram",
};

function modeLabel(mode: LineStatus["mode"]): string {
	return MODE_LABELS[mode];
}

export default async function NetworkNowPage() {
	let lines: LineStatus[] | null = null;
	let errorDetail: string | null = null;

	try {
		lines = await getStatusLive();
	} catch (err) {
		errorDetail = err instanceof Error ? err.message : "Unknown error";
	}

	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-12">
			<header className="flex flex-col gap-1">
				<h1 className="font-heading text-2xl font-semibold tracking-tight">
					Network Now
				</h1>
				<p className="text-sm text-muted-foreground">
					Live operational status across the served TfL lines.
				</p>
			</header>

			{errorDetail ? (
				<Alert role="alert">
					<AlertTitle>Live status unavailable</AlertTitle>
					<AlertDescription>{errorDetail}</AlertDescription>
				</Alert>
			) : lines && lines.length === 0 ? (
				<Alert>
					<AlertTitle>No lines reported</AlertTitle>
					<AlertDescription>
						The API returned no line-status rows in the freshness window.
					</AlertDescription>
				</Alert>
			) : (
				<section
					aria-label="Line statuses"
					className="flex flex-col gap-3"
					data-testid="line-status-list"
				>
					{(lines ?? []).map((line) => (
						<Card key={line.line_id}>
							<CardHeader>
								<CardTitle className="flex flex-wrap items-center gap-2">
									<span>{line.line_name}</span>
									<Badge variant="outline">{modeLabel(line.mode)}</Badge>
								</CardTitle>
								<CardDescription className="flex flex-wrap items-center gap-2">
									<StatusBadge
										severity={line.status_severity}
										description={line.status_severity_description}
									/>
									<span aria-hidden>·</span>
									<span>{formatWindow(line)} (Europe/London)</span>
								</CardDescription>
							</CardHeader>
							{line.reason ? (
								<CardContent className="text-sm text-muted-foreground">
									{line.reason}
								</CardContent>
							) : null}
						</Card>
					))}
				</section>
			)}
		</main>
	);
}
