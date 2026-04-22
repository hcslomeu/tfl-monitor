const DEFAULT_API_URL = "http://localhost:8000";

function baseUrl(): string {
	return process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL;
}

export class ApiError extends Error {
	constructor(
		public readonly status: number,
		public readonly detail: string,
	) {
		super(`tfl-monitor API ${status}: ${detail}`);
		this.name = "ApiError";
	}
}

export async function apiFetch<T>(
	path: string,
	init?: RequestInit,
): Promise<T> {
	const response = await fetch(`${baseUrl()}${path}`, {
		...init,
		headers: {
			Accept: "application/json",
			...(init?.headers ?? {}),
		},
	});

	if (!response.ok) {
		let detail = response.statusText;
		try {
			const problem = (await response.json()) as {
				detail?: string;
				title?: string;
			};
			detail = problem.detail ?? problem.title ?? detail;
		} catch {
			// Response body was not JSON; keep status text.
		}
		throw new ApiError(response.status, detail);
	}

	return (await response.json()) as T;
}
