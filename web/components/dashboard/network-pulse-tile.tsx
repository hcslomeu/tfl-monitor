"use client";

import { Card } from "@/components/ui/card";
import type { LineStatus } from "@/lib/api/status-live";

interface NetworkPulseTileProps {
	lines: LineStatus[];
}

interface Pulse {
	tube: { good: number; total: number };
	all: { good: number; total: number };
	bySeverity: { severe: number; degraded: number; good: number };
}

const TFL_SEVERITY = {
	GOOD_SERVICE: 10,
	PART_CLOSURE: 18,
	MINOR_DELAYS: 9,
	SEVERE_DELAYS: 8,
	PART_SUSPENDED: 7,
	SUSPENDED: 6,
	PLANNED_CLOSURE: 5,
	PART_WORKS: 4,
	SPECIAL_SERVICE: 3,
	REDUCED_SERVICE: 2,
	BUS_SERVICE: 1,
	CLOSED: 0,
	ISSUES: 11,
	NO_STEP_FREE: 12,
	CHANGE_OF_FREQ: 13,
	DIVERTED: 14,
	NOT_RUNNING: 15,
	RAIL_SUSP: 16,
	INFORMATION: 17,
	SPECIAL_CLOSING: 20,
} as const;

const SEVERE = new Set<number>([
	TFL_SEVERITY.CLOSED,
	TFL_SEVERITY.BUS_SERVICE,
	TFL_SEVERITY.REDUCED_SERVICE,
	TFL_SEVERITY.SPECIAL_SERVICE,
	TFL_SEVERITY.PART_WORKS,
	TFL_SEVERITY.PLANNED_CLOSURE,
	TFL_SEVERITY.SUSPENDED,
	TFL_SEVERITY.RAIL_SUSP,
	TFL_SEVERITY.SPECIAL_CLOSING,
]);
const DEGRADED = new Set<number>([
	TFL_SEVERITY.PART_SUSPENDED,
	TFL_SEVERITY.SEVERE_DELAYS,
	TFL_SEVERITY.MINOR_DELAYS,
	TFL_SEVERITY.ISSUES,
	TFL_SEVERITY.NO_STEP_FREE,
	TFL_SEVERITY.CHANGE_OF_FREQ,
	TFL_SEVERITY.DIVERTED,
	TFL_SEVERITY.NOT_RUNNING,
	TFL_SEVERITY.INFORMATION,
]);
const GOOD = new Set<number>([
	TFL_SEVERITY.GOOD_SERVICE,
	TFL_SEVERITY.PART_CLOSURE,
]);

function pulse(lines: LineStatus[]): Pulse {
	const tube = lines.filter((l) => l.mode === "tube");
	const goodTube = tube.filter((l) => GOOD.has(l.status_severity)).length;
	const goodAll = lines.filter((l) => GOOD.has(l.status_severity)).length;

	let severe = 0;
	let degraded = 0;
	let good = 0;
	for (const l of lines) {
		if (SEVERE.has(l.status_severity)) severe += 1;
		else if (DEGRADED.has(l.status_severity)) degraded += 1;
		else if (GOOD.has(l.status_severity)) good += 1;
	}

	return {
		tube: { good: goodTube, total: tube.length },
		all: { good: goodAll, total: lines.length },
		bySeverity: { severe, degraded, good },
	};
}

export function NetworkPulseTile({ lines }: NetworkPulseTileProps) {
	const p = pulse(lines);
	const allPct =
		p.all.total > 0 ? Math.round((p.all.good / p.all.total) * 1000) / 10 : 0;

	return (
		<Card className="flex items-center gap-6 px-4 py-3">
			<div>
				<div className="text-[10px] uppercase tracking-wider text-muted-foreground">
					Network pulse
				</div>
				<div className="mt-1 text-2xl font-bold">
					{p.tube.good} of {p.tube.total}
					<span className="ml-2 text-sm font-medium text-muted-foreground">
						Tube lines
					</span>
				</div>
				<div className="text-xs text-emerald-600 dark:text-emerald-500">
					running good service
				</div>
			</div>

			<div className="flex flex-1 items-center gap-3">
				<Dot
					label="severe"
					count={p.bySeverity.severe}
					className="bg-red-600"
				/>
				<Dot
					label="degraded"
					count={p.bySeverity.degraded}
					className="bg-amber-500"
				/>
				<Dot
					label="good"
					count={p.bySeverity.good}
					className="bg-emerald-600"
				/>
			</div>

			<div className="text-right text-[11px] text-muted-foreground">
				Across all modes:
				<br />
				<b className="text-foreground">
					{p.all.good} of {p.all.total} lines · {allPct}%
				</b>
			</div>
		</Card>
	);
}

function Dot({
	label,
	count,
	className,
}: {
	label: string;
	count: number;
	className: string;
}) {
	return (
		<div
			className="flex flex-col items-center"
			role="img"
			aria-label={`${label} lines: ${count}`}
		>
			<span className={`size-3.5 rounded-full ${className}`} />
			<span className="mt-1 text-[10px] font-medium">{count}</span>
		</div>
	);
}
