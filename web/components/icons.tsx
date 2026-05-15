import type * as React from "react";

const baseProps = {
	viewBox: "0 0 24 24",
	fill: "none",
	stroke: "currentColor",
	strokeWidth: 1.5,
	strokeLinecap: "round" as const,
	strokeLinejoin: "round" as const,
} as const;

type IconProps = React.SVGProps<SVGSVGElement> & { size?: number };

function brand(d: React.ReactNode) {
	return function BrandIcon({ size = 18, ...rest }: IconProps) {
		return (
			<svg
				width={size}
				height={size}
				aria-hidden="true"
				{...baseProps}
				{...rest}
			>
				{d}
			</svg>
		);
	};
}

export const GithubIcon = brand(
	<>
		<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 1.5 5 1.5 5 1.5c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 8.5c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
		<path d="M9 18c-4.51 2-5-2-7-2" />
	</>,
);

export const LinkedinIcon = brand(
	<>
		<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6z" />
		<rect width="4" height="12" x="2" y="9" />
		<circle cx="4" cy="4" r="2" />
	</>,
);

export const XIcon = brand(
	<path d="M18 2h3l-7.5 8.6L22 22h-6.7l-5.2-6.8L4.2 22H1.2l8-9.2L1 2h6.8l4.7 6.2L18 2z" />,
);

export const AtSignIcon = brand(
	<>
		<circle cx="12" cy="12" r="4" />
		<path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94" />
	</>,
);

export const SendIcon = brand(
	<>
		<path d="M12 19V5" />
		<path d="m5 12 7-7 7 7" />
	</>,
);

export const ArrowRightIcon = brand(
	<>
		<path d="M5 12h14" />
		<path d="m12 5 7 7-7 7" />
	</>,
);

type UpworkIconProps = IconProps & { monochrome?: boolean };
export function UpworkIcon({
	size = 18,
	monochrome = false,
	...rest
}: UpworkIconProps) {
	const viewBox = monochrome ? "51 69 410 410" : "0 0 512 512";
	return (
		<svg
			width={size}
			height={size}
			viewBox={viewBox}
			aria-hidden="true"
			{...rest}
		>
			{!monochrome && <rect width="512" height="512" rx="76" fill="#000" />}
			<path
				fill={monochrome ? "currentColor" : "#fff"}
				d="M357.2,296.9c-17,0-33-7.2-47.4-18.9l3.5-16.6l0.1-.6c3.2-17.6,13.1-47.2,43.8-47.2c23,0,41.7,18.7,41.7,41.7S380.2,296.9,357.2,296.9L357.2,296.9z M357.2,171.4c-39.2,0-69.5,25.4-81.9,67.3c-18.8-28.3-33.1-62.2-41.4-90.8h-42.2v109.7c0,21.7-17.6,39.3-39.3,39.3s-39.3-17.6-39.3-39.3V147.8H71v109.7c0,44.9,36.5,81.8,81.4,81.8s81.4-36.9,81.4-81.8v-18.4c8.2,17.1,18.2,34.4,30.4,49.6l-25.8,121.4h43.1l18.7-88c16.4,10.5,35.2,17.1,56.8,17.1c46.2,0,83.8-37.8,83.8-84.1C440.9,209,403.4,171.4,357.2,171.4"
			/>
		</svg>
	);
}

export const AudioIcon = brand(
	<>
		<path d="M2 10v3" />
		<path d="M6 6v11" />
		<path d="M10 3v18" />
		<path d="M14 8v7" />
		<path d="M18 5v13" />
		<path d="M22 10v3" />
	</>,
);
