/**
 * Inline SVG icon used across the dashboard surface.
 *
 * Path strings are exported as constants so callers reference them by
 * name. The renderer splits multi-subpath strings on every leading `M`
 * so the upstream design-system path data round-trips unchanged.
 */

export const GITHUB_PATH =
	"M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 1.5 5 1.5 5 1.5c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 8.5c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4M9 18c-4.51 2-5-2-7-2";

export const SEND_PATH = "M12 19V5 M5 12 l7-7 7 7";

export const AUDIO_PATH = "M2 10v3 M6 6v11 M10 3v18 M14 8v7 M18 5v13 M22 10v3";

export interface IconProps {
	d: string;
	size?: number;
}

export function Icon({ d, size = 16 }: IconProps) {
	const parts = d.split(/(?=M)/).filter(Boolean);
	return (
		<svg
			width={size}
			height={size}
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.5"
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
		>
			{parts.map((p) => (
				<path key={p} d={p} />
			))}
		</svg>
	);
}
