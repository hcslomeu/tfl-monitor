/**
 * Minimal SSE parser for the `/chat/stream` event-stream.
 *
 * The backend (`src/api/agent/streaming.py`) emits one JSON payload
 * per `data:` line, terminated by a blank line. `EventSourceResponse`
 * also injects `: ping` comments every 15s — those lines are skipped.
 */

export type Frame =
	| { type: "token"; content: string }
	| { type: "tool"; content: string }
	| { type: "end"; content: string };

export class SSEParser {
	private buffer = "";
	private decoder = new TextDecoder();

	push(chunk: Uint8Array): Frame[] {
		this.buffer += this.decoder.decode(chunk, { stream: true });

		const frames: Frame[] = [];
		let boundary = this.buffer.indexOf("\n\n");
		while (boundary !== -1) {
			const event = this.buffer.slice(0, boundary);
			this.buffer = this.buffer.slice(boundary + 2);
			const parsed = parseEvent(event);
			if (parsed) frames.push(parsed);
			boundary = this.buffer.indexOf("\n\n");
		}
		return frames;
	}
}

function parseEvent(event: string): Frame | null {
	const dataLines: string[] = [];
	for (const rawLine of event.split("\n")) {
		const line = rawLine.replace(/\r$/, "");
		if (line === "" || line.startsWith(":")) continue;
		if (line.startsWith("data:")) {
			dataLines.push(line.slice(5).trimStart());
		}
	}
	if (dataLines.length === 0) return null;

	try {
		const payload = JSON.parse(dataLines.join("\n")) as unknown;
		if (
			typeof payload === "object" &&
			payload !== null &&
			"type" in payload &&
			"content" in payload &&
			typeof (payload as { type: unknown }).type === "string" &&
			typeof (payload as { content: unknown }).content === "string"
		) {
			const { type, content } = payload as { type: string; content: string };
			if (type === "token" || type === "tool" || type === "end") {
				return { type, content };
			}
		}
	} catch {
		// Malformed JSON — drop the frame rather than crashing the stream.
	}
	return null;
}
