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
		return [];
	}
}
