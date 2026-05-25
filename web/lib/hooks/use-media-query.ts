"use client";

import { useEffect, useState } from "react";

/**
 * Tracks whether a CSS media query currently matches.
 *
 * Returns `false` during server render and the first client paint, so callers
 * must treat the non-matching (typically desktop) layout as the SSR default
 * and let the post-mount effect correct it.
 *
 * @param query Media query string, e.g. `"(max-width: 880px)"`
 * @returns Whether the query matches the current viewport
 */
export function useMediaQuery(query: string): boolean {
	const [matches, setMatches] = useState(false);

	useEffect(() => {
		if (typeof window === "undefined" || !window.matchMedia) return;
		const mql = window.matchMedia(query);
		setMatches(mql.matches);
		const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
		// Safari/iOS <= 13 expose only the legacy addListener/removeListener API.
		if (mql.addEventListener) {
			mql.addEventListener("change", onChange);
			return () => mql.removeEventListener("change", onChange);
		}
		mql.addListener(onChange);
		return () => mql.removeListener(onChange);
	}, [query]);

	return matches;
}
