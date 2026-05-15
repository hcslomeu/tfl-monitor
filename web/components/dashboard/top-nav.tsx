"use client";

import { GITHUB_PATH, Icon } from "./icons";
import type { StatusSummaryCounts } from "./types";

export interface TopNavProps {
	summary: StatusSummaryCounts;
	clockLabel: string;
	repoUrl?: string;
}

const REPO_URL_DEFAULT = "https://github.com/humbertolomeu/tfl-monitor";

export function TopNav({
	summary,
	clockLabel,
	repoUrl = REPO_URL_DEFAULT,
}: TopNavProps) {
	return (
		<nav className="tfl-nav">
			<div className="tfl-nav-side tfl-nav-left">
				<div className="tfl-brand">TfL Monitor</div>
				<span className="tfl-nav-divider" />
				<a
					className="tfl-nav-iconbtn"
					href={repoUrl}
					aria-label="GitHub repo"
					target="_blank"
					rel="noopener noreferrer"
				>
					<Icon d={GITHUB_PATH} size={15} />
				</a>
			</div>
			<div className="tfl-nav-side tfl-nav-right">
				<div className="tfl-nav-status">
					<div className="tfl-nav-sep">
						<span className="tfl-nav-sep-line" />
						<span className="tfl-nav-sep-label">Status</span>
					</div>
					<div className="tfl-nav-summary">
						<span className="seg">
							<span className="pill" style={{ background: "var(--success)" }} />
							{summary.good} good
						</span>
						<span className="seg">
							<span className="pill" style={{ background: "var(--warning)" }} />
							{summary.minor} minor
						</span>
						<span className="seg">
							<span className="pill" style={{ background: "var(--danger)" }} />
							{summary.severe} severe
						</span>
						<span className="seg">
							<span
								className="pill"
								style={{ background: "var(--ink-primary)" }}
							/>
							{summary.suspended} suspended
						</span>
					</div>
				</div>
				<span className="tfl-nav-clock">{clockLabel}</span>
			</div>
		</nav>
	);
}
