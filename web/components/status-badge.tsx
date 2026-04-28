import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Severity bands mirror TfL's status-severity scale (0..20).
 *
 * - 10 = "Good Service" → green/default tone.
 * - 7..9 = "Minor Delays" / "Part Closure" → amber/secondary tone.
 * - <= 6 = severe delays / suspended / "Service Closed" → red/destructive
 *   tone.
 * - >= 11 = "Part Closed" / "Planned Closure" / "Service Closed" — the
 *   higher half of the scale is *still* disruptive. Only severity 10 is
 *   the good-service signal.
 */
export type StatusBadgeProps = {
	severity: number;
	description: string;
	className?: string;
};

function tone(severity: number): "good" | "minor" | "severe" {
	if (severity === 10) return "good";
	if (severity >= 7 && severity <= 9) return "minor";
	return "severe";
}

export function StatusBadge({
	severity,
	description,
	className,
}: StatusBadgeProps) {
	const band = tone(severity);

	if (band === "good") {
		return (
			<Badge
				data-tone="good"
				className={cn(
					"bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200",
					className,
				)}
			>
				{description}
			</Badge>
		);
	}

	if (band === "minor") {
		return (
			<Badge
				variant="secondary"
				data-tone="minor"
				className={cn(
					"bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200",
					className,
				)}
			>
				{description}
			</Badge>
		);
	}

	return (
		<Badge variant="destructive" data-tone="severe" className={className}>
			{description}
		</Badge>
	);
}
