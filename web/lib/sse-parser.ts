/**
 * Minimal SSE parser for the `/chat/stream` event-stream.
 *
 * The backend (`src/api/agent/streaming.py`) emits one JSON payload
 * per `data:` line, terminated by a blank line. `EventSourceResponse`
 * also injects `: ping` comments every 15s — those lines are skipped.
 *
 * Per the SSE spec (https://html.spec.whatwg.org/multipage/server-sent-events.html),
 * event boundaries may be `\n\n`, `\r\n\r\n`, or `\r\r`, and individual line
 * terminators may be `\n`, `\r\n`, or a standalone `\r`. sse-starlette's
 * default `sep` is `\r\n`, so prod traffic typically uses CRLF.
 */

export type Frame =
	| { type: "token"; content: string }
	| { type: "tool"; content: string }
	| { type: "end"; content: string };

const EVENT_BOUNDARY = /\r\n\r\n|\r\r|\n\n/;
const LINE_TERMINATOR = /\r\n|\r|\n/;

export class SSEParser {
	private buffer = "";
	private decoder = new TextDecoder();

	push(chunk: Uint8Array): Frame[] {
		this.buffer += this.decoder.decode(chunk, { stream: true });

		const frames: Frame[] = [];
		while (true) {
			const match = this.buffer.match(EVENT_BOUNDARY);
			if (!match || match.index === undefined) break;
			const event = this.buffer.slice(0, match.index);
			this.buffer = this.buffer.slice(match.index + match[0].length);
			const parsed = parseEvent(event);
			if (parsed) frames.push(parsed);
		}
		return frames;
	}
}

function parseEvent(event: string): Frame | null {
	const dataLines: string[] = [];
	for (const line of event.split(LINE_TERMINATOR)) {
		if (line === "" || line.startsWith(":")) continue;
		if (line.startsWith("data:")) {
			// SSE spec: drop only the single space directly after `data:`,
			// not all leading whitespace (a payload may begin with a space).
			dataLines.push(line.slice(5).replace(/^ /, ""));
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
