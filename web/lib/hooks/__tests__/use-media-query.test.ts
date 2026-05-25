import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMediaQuery } from "@/lib/hooks/use-media-query";

type ChangeListener = (event: MediaQueryListEvent) => void;

/**
 * Installs a controllable `window.matchMedia` stub and returns helpers to flip
 * the match state and inspect listener bookkeeping. When `legacy` is set, the
 * stub omits `addEventListener`/`removeEventListener` to emulate Safari/iOS 13.
 */
function mockMatchMedia({
	matches,
	legacy = false,
}: {
	matches: boolean;
	legacy?: boolean;
}) {
	const listeners = new Set<ChangeListener>();
	const mql: Record<string, unknown> = { matches, media: "", onchange: null };

	if (legacy) {
		mql.addListener = (cb: ChangeListener) => listeners.add(cb);
		mql.removeListener = (cb: ChangeListener) => listeners.delete(cb);
	} else {
		mql.addEventListener = (_: string, cb: ChangeListener) => listeners.add(cb);
		mql.removeEventListener = (_: string, cb: ChangeListener) =>
			listeners.delete(cb);
	}

	Object.defineProperty(window, "matchMedia", {
		configurable: true,
		value: vi.fn(() => mql as unknown as MediaQueryList),
	});

	return {
		emit(next: boolean) {
			mql.matches = next;
			for (const cb of listeners) {
				cb({ matches: next } as MediaQueryListEvent);
			}
		},
		listenerCount: () => listeners.size,
	};
}

describe("useMediaQuery", () => {
	afterEach(() => {
		mockMatchMedia({ matches: false });
	});

	it("reflects the current match state after mount", () => {
		mockMatchMedia({ matches: true });
		const { result } = renderHook(() => useMediaQuery("(max-width: 880px)"));
		expect(result.current).toBe(true);
	});

	it("updates when the query match changes", () => {
		const mq = mockMatchMedia({ matches: true });
		const { result } = renderHook(() => useMediaQuery("(max-width: 880px)"));
		expect(result.current).toBe(true);

		act(() => mq.emit(false));
		expect(result.current).toBe(false);
	});

	it("removes its listener on unmount", () => {
		const mq = mockMatchMedia({ matches: true });
		const { unmount } = renderHook(() => useMediaQuery("(max-width: 880px)"));
		expect(mq.listenerCount()).toBe(1);

		unmount();
		expect(mq.listenerCount()).toBe(0);
	});

	it("falls back to the legacy addListener API", () => {
		const mq = mockMatchMedia({ matches: false, legacy: true });
		const { result } = renderHook(() => useMediaQuery("(max-width: 880px)"));
		expect(mq.listenerCount()).toBe(1);

		act(() => mq.emit(true));
		expect(result.current).toBe(true);
	});
});
