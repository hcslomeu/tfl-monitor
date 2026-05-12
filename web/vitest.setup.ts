import "@testing-library/jest-dom/vitest";

// Node 22+ ships a native `localStorage` that requires a `--localstorage-file`
// flag, which jsdom 29 picks up under Node and fails on. Stub an in-memory
// implementation so component tests can exercise persistence logic.
function createMemoryStorage(): Storage {
	const store = new Map<string, string>();
	return {
		get length(): number {
			return store.size;
		},
		clear(): void {
			store.clear();
		},
		getItem(key: string): string | null {
			return store.has(key) ? (store.get(key) as string) : null;
		},
		setItem(key: string, value: string): void {
			store.set(key, String(value));
		},
		removeItem(key: string): void {
			store.delete(key);
		},
		key(index: number): string | null {
			return Array.from(store.keys())[index] ?? null;
		},
	};
}

// jsdom 29 omits `matchMedia`; vaul (drawer primitive) calls it on mount.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
	Object.defineProperty(window, "matchMedia", {
		configurable: true,
		writable: true,
		value: (query: string): MediaQueryList => ({
			matches: false,
			media: query,
			onchange: null,
			addListener: () => {},
			removeListener: () => {},
			addEventListener: () => {},
			removeEventListener: () => {},
			dispatchEvent: () => false,
		}),
	});
}

for (const name of ["localStorage", "sessionStorage"] as const) {
	const storage = createMemoryStorage();
	Object.defineProperty(globalThis, name, {
		configurable: true,
		value: storage,
	});
	if (typeof window !== "undefined") {
		Object.defineProperty(window, name, {
			configurable: true,
			value: storage,
		});
	}
}
