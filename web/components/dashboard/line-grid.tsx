// biome-ignore-all lint/a11y/useSemanticElements: <div role="button"> preserves the upstream design-system CSS that styles every `.tfl-line` row; switching to <button> would inherit user-agent defaults the CSS does not reset, and keyboard activation is wired explicitly below.
"use client";

import { Fragment, type KeyboardEvent, type ReactNode } from "react";

import { CLOSE_PATH, Icon } from "./icons";
import type { LineSummary } from "./types";

export interface LineGridProps {
	lines: LineSummary[];
	selected?: string;
	onSelect: (code: string) => void;
	/**
	 * Detail panel for the selected line, rendered inline beneath the active
	 * row as an accordion. The caller supplies this only on the stacked mobile
	 * layout and passes `null` on desktop, where the detail lives in the right
	 * column instead.
	 */
	detail?: ReactNode;
	/**
	 * Collapses the inline detail. Wired to the accordion's close button, which
	 * only renders alongside `detail` (i.e. on the stacked mobile layout).
	 */
	onCloseDetail?: () => void;
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

export function LineGrid({
	lines,
	selected,
	onSelect,
	detail,
	onCloseDetail,
}: LineGridProps) {
	return (
		<section className="tfl-card tfl-left-col">
			<div className="tfl-card-h">
				<h4>Tube, Overground, DLR &amp; Elizabeth</h4>
				<span className="meta">tap a line</span>
			</div>
			<div className="tfl-line-list">
				{lines.map((l) => {
					const isActive = selected === l.code;
					const activate = () => onSelect(l.code);
					return (
						<Fragment key={l.code}>
							<div
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
							{isActive && detail ? (
								<div className="tfl-line-detail-inline">
									{onCloseDetail ? (
										<button
											type="button"
											className="tfl-line-detail-close"
											onClick={onCloseDetail}
											aria-label="Hide line details"
										>
											<Icon d={CLOSE_PATH} size={16} />
										</button>
									) : null}
									{detail}
								</div>
							) : null}
						</Fragment>
					);
				})}
			</div>
		</section>
	);
}
