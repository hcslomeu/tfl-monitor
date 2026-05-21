import { Analytics } from "@vercel/analytics/next";
import type { Metadata } from "next";
import { Geist, Inter, JetBrains_Mono } from "next/font/google";
import localFont from "next/font/local";

import { Footer } from "@/components/layout/footer";
import "./globals.css";

const editorial = localFont({
	src: [
		{
			path: "../public/fonts/PPEditorialNew-Ultralight.otf",
			weight: "200",
			style: "normal",
		},
		{
			path: "../public/fonts/PPEditorialNew-UltralightItalic.otf",
			weight: "200",
			style: "italic",
		},
		{
			path: "../public/fonts/PPEditorialNew-Regular.otf",
			weight: "400",
			style: "normal",
		},
		{
			path: "../public/fonts/PPEditorialNew-Italic.otf",
			weight: "400",
			style: "italic",
		},
		{
			path: "../public/fonts/PPEditorialNew-Ultrabold.otf",
			weight: "800",
			style: "normal",
		},
		{
			path: "../public/fonts/PPEditorialNew-UltraboldItalic.otf",
			weight: "800",
			style: "italic",
		},
	],
	variable: "--font-display-local",
	display: "swap",
});

const inter = Inter({
	subsets: ["latin"],
	variable: "--font-body-local",
	display: "swap",
});

const jetbrains = JetBrains_Mono({
	subsets: ["latin"],
	variable: "--font-mono-local",
	display: "swap",
});

const geist = Geist({
	subsets: ["latin"],
	variable: "--font-wordmark-local",
	display: "swap",
});

const SITE_URL = "https://tfl-monitor.humbertolomeu.com";
const SITE_TITLE = "TfL Monitor — London transport at a glance";
const SITE_DESCRIPTION =
	"Real-time London transport status dashboard — Tube, Overground, DLR, Elizabeth line, buses, and disruptions.";

export const metadata: Metadata = {
	metadataBase: new URL(SITE_URL),
	title: SITE_TITLE,
	description: SITE_DESCRIPTION,
	icons: {
		icon: [
			{ url: "/favicon.svg", type: "image/svg+xml" },
			{ url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
			{ url: "/favicon-16.png", sizes: "16x16", type: "image/png" },
			{ url: "/favicon-192.png", sizes: "192x192", type: "image/png" },
			{ url: "/favicon-512.png", sizes: "512x512", type: "image/png" },
		],
		apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
	},
	openGraph: {
		type: "website",
		url: SITE_URL,
		title: SITE_TITLE,
		description: SITE_DESCRIPTION,
		images: [{ url: "/og.png", width: 1200, height: 630 }],
	},
	twitter: {
		card: "summary_large_image",
		title: SITE_TITLE,
		description: SITE_DESCRIPTION,
		images: ["/og.png"],
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	const fontVariables = [
		editorial.variable,
		inter.variable,
		jetbrains.variable,
		geist.variable,
	].join(" ");

	return (
		<html lang="en" className={fontVariables}>
			<body className="density-product">
				<div className="hl-shell">
					<div className="hl-shell-main">{children}</div>
					<Footer />
				</div>
				<Analytics />
			</body>
		</html>
	);
}
