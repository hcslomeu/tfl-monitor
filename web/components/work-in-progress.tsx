"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
	label?: string;
	storageKey?: string;
	anchorSelector?: string;
};

export function WorkInProgress({
	label = "Still building this — more features soon",
	storageKey = "hl-wip-dismissed",
	anchorSelector = ".hl-nav",
}: Props) {
	const [mounted, setMounted] = useState(false);
	const [dismissed, setDismissed] = useState(false);
	const asideRef = useRef<HTMLElement | null>(null);

	useEffect(() => {
		setMounted(true);
		setDismissed(window.localStorage.getItem(storageKey) === "1");
	}, [storageKey]);

	useEffect(() => {
		if (!mounted || dismissed) return;
		const anchor = document.querySelector(anchorSelector) as HTMLElement | null;
		const aside = asideRef.current;
		if (!anchor || !aside) return;

		const update = () => {
			const rect = anchor.getBoundingClientRect();
			const rightOffset = document.documentElement.clientWidth - rect.right;
			aside.style.right = `${Math.max(rightOffset, 8)}px`;
		};

		update();
		const ro = new ResizeObserver(update);
		ro.observe(anchor);
		window.addEventListener("resize", update);
		return () => {
			ro.disconnect();
			window.removeEventListener("resize", update);
		};
	}, [mounted, dismissed, anchorSelector]);

	if (!mounted || dismissed) return null;

	const dismiss = () => {
		window.localStorage.setItem(storageKey, "1");
		setDismissed(true);
	};

	return (
		<aside ref={asideRef} className="hl-wip" role="status" aria-live="polite">
			<span className="hl-wip-dots" aria-hidden>
				<span />
				<span />
				<span />
			</span>
			<span className="hl-wip-label">{label}</span>
			<button
				type="button"
				className="hl-wip-close"
				aria-label="Dismiss work in progress notice"
				onClick={dismiss}
			>
				×
			</button>
		</aside>
	);
}
