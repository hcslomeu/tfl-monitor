import type { NextConfig } from "next";

const securityHeaders = [
	{ key: "X-Frame-Options", value: "DENY" },
	{ key: "X-Content-Type-Options", value: "nosniff" },
	{ key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
	{
		key: "Permissions-Policy",
		value: "camera=(), microphone=(), geolocation=()",
	},
];

const nextConfig: NextConfig = {
	async headers() {
		return [{ source: "/(.*)", headers: securityHeaders }];
	},
	async redirects() {
		return [
			{ source: "/disruptions", destination: "/", permanent: true },
			{ source: "/reliability", destination: "/", permanent: true },
			{ source: "/ask", destination: "/", permanent: true },
		];
	},
};

export default nextConfig;
