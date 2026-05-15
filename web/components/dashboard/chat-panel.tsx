"use client";

import { useEffect, useRef, useState } from "react";

import { streamChat } from "@/lib/api/chat-stream";
import { ApiError } from "@/lib/api-client";
import { AUDIO_PATH, Icon, SEND_PATH } from "./icons";

export interface QuickPrompt {
	label: string;
	value: string;
}

export interface ChatPanelProps {
	placeholder?: string;
	quickPrompts?: QuickPrompt[];
}

type Role = "user" | "assistant";

interface RenderableMessage {
	id: string;
	role: Role;
	content: string;
	errored?: boolean;
}

const DEFAULT_PLACEHOLDER =
	"what is the next train leaving Baker Street to Uxbridge?";

const DEFAULT_QUICK_PROMPTS: QuickPrompt[] = [
	{ label: "Next train", value: "Next train Baker Street → Uxbridge" },
	{ label: "Why delayed?", value: "Why is the Elizabeth line delayed?" },
	{
		label: "Ticket acceptance",
		value: "Tickets accepted on which lines?",
	},
];

export function ChatPanel({
	placeholder = DEFAULT_PLACEHOLDER,
	quickPrompts = DEFAULT_QUICK_PROMPTS,
}: ChatPanelProps) {
	const threadIdRef = useRef<string | null>(null);
	if (threadIdRef.current === null) {
		threadIdRef.current = crypto.randomUUID();
	}

	const [value, setValue] = useState("");
	const [messages, setMessages] = useState<RenderableMessage[]>([]);
	const [busy, setBusy] = useState(false);
	const [toolStatus, setToolStatus] = useState<string | null>(null);
	const [serviceError, setServiceError] = useState<string | null>(null);
	const transcriptRef = useRef<HTMLDivElement | null>(null);

	// biome-ignore lint/correctness/useExhaustiveDependencies: scroll-to-bottom must re-run whenever the transcript grows, even though the effect body only touches the ref.
	useEffect(() => {
		const node = transcriptRef.current;
		if (node) {
			node.scrollTop = node.scrollHeight;
		}
	}, [messages, toolStatus]);

	async function send() {
		const trimmed = value.trim();
		if (!trimmed || busy) return;

		setValue("");
		setBusy(true);
		setServiceError(null);
		setToolStatus(null);
		setMessages((prev) => [
			...prev,
			{ id: crypto.randomUUID(), role: "user", content: trimmed },
			{ id: crypto.randomUUID(), role: "assistant", content: "" },
		]);

		try {
			let assistantContent = "";
			let endedWithError = false;
			for await (const frame of streamChat({
				thread_id: threadIdRef.current as string,
				message: trimmed,
			})) {
				if (frame.type === "token") {
					assistantContent += frame.content;
					setToolStatus(null);
					setMessages((prev) => {
						const next = [...prev];
						const last = next[next.length - 1];
						next[next.length - 1] = { ...last, content: assistantContent };
						return next;
					});
				} else if (frame.type === "tool") {
					setToolStatus(`Using tool: ${frame.content}…`);
				} else if (frame.type === "end") {
					endedWithError = frame.content === "error";
				}
			}
			if (endedWithError) {
				setMessages((prev) => {
					const next = [...prev];
					const last = next[next.length - 1];
					next[next.length - 1] = {
						...last,
						content: assistantContent || "Stream interrupted.",
						errored: true,
					};
					return next;
				});
			}
		} catch (err) {
			setMessages((prev) => prev.slice(0, -2));
			if (err instanceof ApiError) {
				setServiceError(err.detail || `HTTP ${err.status}`);
			} else if (err instanceof Error && err.message) {
				setServiceError(err.message);
			} else {
				setServiceError("Unknown error");
			}
		} finally {
			setBusy(false);
			setToolStatus(null);
		}
	}

	const canSend = !busy && value.trim().length > 0;

	return (
		<div className="tfl-chat-stack">
			<section className="tfl-card tfl-chat-card">
				<div className="tfl-chat-card-h">
					<h4>Ask the Monitor</h4>
					<span className="meta">GPT · context · TfL</span>
				</div>
				{serviceError ? (
					<div role="alert" className="tfl-chat-alert">
						<strong>Agent unavailable.</strong> {serviceError}
					</div>
				) : null}
				<div
					className="tfl-chat-transcript"
					ref={transcriptRef}
					aria-live="polite"
				>
					{messages.length > 0 ? (
						<ul
							aria-label="Conversation"
							data-testid="conversation"
							style={{
								display: "flex",
								flexDirection: "column",
								gap: 10,
								listStyle: "none",
								margin: 0,
								padding: 0,
							}}
						>
							{messages.map((message, index) => {
								const isLast = index === messages.length - 1;
								const showSkeleton =
									busy &&
									isLast &&
									message.role === "assistant" &&
									message.content === "";
								const who = message.role === "user" ? "user" : "bot";
								return (
									<li
										key={message.id}
										className={`tfl-msg tfl-msg-${who}`}
										data-role={message.role}
										data-errored={message.errored ? "true" : undefined}
									>
										{who === "bot" ? (
											<span className="tfl-msg-avatar" aria-hidden />
										) : null}
										<span className="tfl-msg-bubble">
											{showSkeleton ? (
												<span
													className="tfl-msg-skel"
													role="status"
													aria-label="Streaming"
												>
													…
												</span>
											) : (
												message.content
											)}
										</span>
									</li>
								);
							})}
						</ul>
					) : null}
					{toolStatus ? (
						<p data-testid="agent-status" className="tfl-chat-tool-status">
							{toolStatus}
						</p>
					) : null}
				</div>
			</section>
			<div className="tfl-chatbox">
				<textarea
					className="tfl-chatbox-ta"
					placeholder={placeholder}
					value={value}
					onChange={(e) => setValue(e.target.value)}
					onKeyDown={(e) => {
						if (
							e.key === "Enter" &&
							!e.shiftKey &&
							!e.nativeEvent.isComposing
						) {
							e.preventDefault();
							send();
						}
					}}
					rows={2}
					maxLength={4000}
					disabled={busy}
				/>
				<div className="tfl-chatbox-row">
					<div className="tfl-chatbox-l">
						{quickPrompts.map((prompt) => (
							<button
								key={prompt.label}
								type="button"
								className="tfl-chip-sm"
								onClick={() => setValue(prompt.value)}
								disabled={busy}
							>
								{prompt.label}
							</button>
						))}
					</div>
					<div className="tfl-chatbox-r">
						<button
							type="button"
							className="tfl-chat-iconbtn"
							aria-label="Voice"
							disabled={busy}
						>
							<Icon d={AUDIO_PATH} size={16} />
						</button>
						<button
							type="button"
							className="tfl-chatbox-send"
							aria-label="Send"
							onClick={send}
							disabled={!canSend}
						>
							<Icon d={SEND_PATH} size={16} />
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}
