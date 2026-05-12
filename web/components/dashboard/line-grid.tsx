// biome-ignore-all lint/a11y/useSemanticElements: <div role="button"> preserves the upstream design-system CSS that styles every `.tfl-line` row; switching to <button> would inherit user-agent defaults the CSS does not reset, and keyboard activation is wired explicitly below.
"use client";

import type { KeyboardEvent } from "react";

import type { LineSummary } from "./types";

export interface LineGridProps {
	lines: LineSummary[];
	selected?: string;
	onSelect: (code: string) => void;
}

function activateOnEnterOrSpace(
	event: KeyboardEvent<HTMLDivElement>,
	handler: () => void,
) {
	if (event.key === "Enter" || event.key === " ") {
		event.preventDefault();
		handler();
	}
}

export function LineGrid({ lines, selected, onSelect }: LineGridProps) {
	return (
		<section className="tfl-card">
			<div className="tfl-card-h">
				<h4>Tube, Overground, DLR &amp; Elizabeth</h4>
				<span className="meta">tap a line</span>
			</div>
			<div className="tfl-line-list">
				{lines.map((l) => {
					const isActive = selected === l.code;
					const activate = () => onSelect(l.code);
					return (
						<div
							key={l.code}
							role="button"
							tabIndex={0}
							className={`tfl-line${isActive ? " active" : ""}`}
							onClick={activate}
							onKeyDown={(e) => activateOnEnterOrSpace(e, activate)}
							aria-pressed={isActive}
						>
							<span
								className="tfl-line-stripe"
								style={{ background: l.color }}
							/>
							<div className="tfl-line-name-wrap">
								<span className="tfl-line-name">{l.name}</span>
								<span className="tfl-line-updated">{l.updatedLabel}</span>
							</div>
							<span className={`tfl-line-status tfl-${l.status}`}>
								<span className="dot" />
								{l.statusText}
							</span>
						</div>
					);
				})}
			</div>
		</section>
	);
}
