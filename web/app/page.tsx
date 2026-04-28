/**
 * Network Now — landing view.
 *
 * Reads from `getStatusLive()`, which is a mock-backed fetcher in
 * TM-E1a. The real `/status/live` wiring lands in TM-E1b once TM-D2
 * connects the FastAPI handler to Postgres. The mock origin and the
 * swap point are documented in `lib/api/status-live.ts`.
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
	const lines = await getStatusLive();

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

			<Alert>
				<AlertTitle>Mock data</AlertTitle>
				<AlertDescription>
					Real <code>/status/live</code> wiring lands in TM-E1b once TM-D2
					connects the FastAPI handler to Postgres. This page renders a
					committed fixture so the layout can be reviewed in isolation.
				</AlertDescription>
			</Alert>

			<section
				aria-label="Line statuses"
				className="flex flex-col gap-3"
				data-testid="line-status-list"
			>
				{lines.map((line) => (
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
		</main>
	);
}
