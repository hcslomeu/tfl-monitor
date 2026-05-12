import type { Metadata } from "next";
import { Geist, Inter, JetBrains_Mono } from "next/font/google";
import localFont from "next/font/local";

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

export const metadata: Metadata = {
	title: "TfL Monitor — London transport at a glance",
	description:
		"Real-time London transport status dashboard — Tube, Overground, DLR, Elizabeth line, buses, and disruptions.",
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
			<body className="density-product">{children}</body>
		</html>
	);
}
