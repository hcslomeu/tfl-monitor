import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAutoRefresh } from "@/lib/hooks/use-auto-refresh";

describe("useAutoRefresh", () => {
	beforeEach(() => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "visible",
		});
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("calls the fetcher once on mount and exposes the result", async () => {
		const fetcher = vi.fn().mockResolvedValue({ ok: true });
		const { result } = renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => {
			expect(fetcher).toHaveBeenCalledTimes(1);
			expect(result.current.data).toEqual({ ok: true });
			expect(result.current.error).toBeNull();
			expect(result.current.lastUpdated).toBeInstanceOf(Date);
		});
	});

	it("re-fetches every interval", async () => {
		const fetcher = vi.fn().mockResolvedValue("data");
		renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

		await act(async () => {
			vi.advanceTimersByTime(1000);
			await Promise.resolve();
		});

		expect(fetcher).toHaveBeenCalledTimes(2);
	});

	it("clears the interval on unmount", async () => {
		const fetcher = vi.fn().mockResolvedValue("data");
		const { unmount } = renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
		unmount();

		act(() => {
			vi.advanceTimersByTime(5000);
		});

		expect(fetcher).toHaveBeenCalledTimes(1);
	});

	it("pauses while the document is hidden and resumes on visibility", async () => {
		const fetcher = vi.fn().mockResolvedValue("data");
		renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "hidden",
		});
		document.dispatchEvent(new Event("visibilitychange"));

		act(() => {
			vi.advanceTimersByTime(2500);
		});
		expect(fetcher).toHaveBeenCalledTimes(1);

		Object.defineProperty(document, "visibilityState", {
			configurable: true,
			value: "visible",
		});
		await act(async () => {
			document.dispatchEvent(new Event("visibilitychange"));
			await Promise.resolve();
		});

		expect(fetcher).toHaveBeenCalledTimes(2);
	});

	it("surfaces fetcher errors on the result", async () => {
		const fetcher = vi.fn().mockRejectedValue(new Error("boom"));
		const { result } = renderHook(() => useAutoRefresh(fetcher, 1000));

		await waitFor(() => {
			expect(result.current.error?.message).toBe("boom");
			expect(result.current.data).toBeNull();
		});
	});
});
