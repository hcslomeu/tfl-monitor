"use client";

import { ExternalLink } from "lucide-react";
import { useCallback } from "react";

import { AboutSheet } from "@/components/about-sheet";
import { ChatPanel } from "@/components/dashboard/chat-panel";
import { ComingUpCard } from "@/components/dashboard/coming-up-card";
import { HappeningNowCard } from "@/components/dashboard/happening-now-card";
import { NetworkPulseTile } from "@/components/dashboard/network-pulse-tile";
import { NetworkStatusCard } from "@/components/dashboard/network-status-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	type Disruption,
	getRecentDisruptions,
} from "@/lib/api/disruptions-recent";
import { getStatusLive, type LineStatus } from "@/lib/api/status-live";
import { useAutoRefresh } from "@/lib/hooks/use-auto-refresh";

const STATUS_INTERVAL_MS = 30_000;
const DISRUPTIONS_INTERVAL_MS = 300_000;

export default function HomePage() {
	const fetchStatus = useCallback(
		(_signal: AbortSignal): Promise<LineStatus[]> => getStatusLive(),
		[],
	);
	const fetchDisruptions = useCallback(
		(_signal: AbortSignal): Promise<Disruption[]> => getRecentDisruptions(),
		[],
	);

	const status = useAutoRefresh(fetchStatus, STATUS_INTERVAL_MS);
	const disruptions = useAutoRefresh(fetchDisruptions, DISRUPTIONS_INTERVAL_MS);

	return (
		<main className="mx-auto max-w-screen-2xl px-6 py-6">
			<header className="mb-6 flex items-center justify-between">
				<div>
					<h1 className="font-heading text-2xl font-semibold tracking-tight">
						tfl-monitor
					</h1>
					<p className="text-sm text-muted-foreground">
						London transport pulse
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Button asChild variant="ghost" size="sm">
						<a
							href="https://github.com/hcslomeu/tfl-monitor"
							target="_blank"
							rel="noopener noreferrer"
							aria-label="GitHub repository"
						>
							<ExternalLink className="size-4" />
							<span>GitHub</span>
						</a>
					</Button>
					<AboutSheet />
				</div>
			</header>

			<div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
				<section className="flex flex-col gap-4">
					{status.error ? (
						<Alert role="alert">
							<AlertTitle>Live status unavailable</AlertTitle>
							<AlertDescription>{status.error.message}</AlertDescription>
						</Alert>
					) : (
						<NetworkStatusCard
							lines={status.data ?? []}
							lastUpdated={status.lastUpdated}
						/>
					)}

					<div className="grid grid-cols-1 gap-4 md:grid-cols-2">
						{disruptions.error ? (
							<Alert role="alert" className="md:col-span-2">
								<AlertTitle>Disruptions unavailable</AlertTitle>
								<AlertDescription>{disruptions.error.message}</AlertDescription>
							</Alert>
						) : (
							<>
								<HappeningNowCard disruptions={disruptions.data ?? []} />
								<ComingUpCard disruptions={disruptions.data ?? []} />
							</>
						)}
					</div>

					<NetworkPulseTile lines={status.data ?? []} />
				</section>

				<ChatPanel />
			</div>
		</main>
	);
}
