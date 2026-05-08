"use client";

import { useEffect, useRef, useState } from "react";

export interface AutoRefreshState<T> {
	data: T | null;
	error: Error | null;
	lastUpdated: Date | null;
}

/**
 * Polls `fetcher` every `intervalMs` milliseconds and exposes the
 * latest snapshot.
 *
 * - Calls once on mount, then on each tick.
 * - Pauses while `document.visibilityState !== "visible"` and resumes
 *   when the tab becomes visible again (battery-friendly + avoids
 *   redundant requests for backgrounded tabs).
 * - Aborts the in-flight request on unmount and on each new tick.
 * - Caller-supplied `fetcher` does not need to be memoised; the hook
 *   captures it through a ref so re-renders don't restart polling.
 */
export function useAutoRefresh<T>(
	fetcher: () => Promise<T>,
	intervalMs: number,
): AutoRefreshState<T> {
	const [data, setData] = useState<T | null>(null);
	const [error, setError] = useState<Error | null>(null);
	const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

	const fetcherRef = useRef(fetcher);
	useEffect(() => {
		fetcherRef.current = fetcher;
	}, [fetcher]);

	useEffect(() => {
		let cancelled = false;
		let timer: ReturnType<typeof setInterval> | null = null;
		let abort: AbortController | null = null;

		const run = async () => {
			abort?.abort();
			abort = new AbortController();
			try {
				const next = await fetcherRef.current();
				if (cancelled) return;
				setData(next);
				setError(null);
				setLastUpdated(new Date());
			} catch (err) {
				if (cancelled) return;
				setError(err instanceof Error ? err : new Error(String(err)));
			}
		};

		const start = () => {
			if (timer !== null) return;
			void run();
			timer = setInterval(run, intervalMs);
		};

		const stop = () => {
			if (timer !== null) {
				clearInterval(timer);
				timer = null;
			}
		};

		const handleVisibility = () => {
			if (document.visibilityState === "visible") {
				start();
			} else {
				stop();
			}
		};

		start();
		document.addEventListener("visibilitychange", handleVisibility);

		return () => {
			cancelled = true;
			stop();
			abort?.abort();
			document.removeEventListener("visibilitychange", handleVisibility);
		};
	}, [intervalMs]);

	return { data, error, lastUpdated };
}
