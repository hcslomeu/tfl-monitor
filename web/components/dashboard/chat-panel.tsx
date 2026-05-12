"use client";

import { useEffect, useId, useRef, useState } from "react";

import { AUDIO_PATH, Icon, SEND_PATH } from "./icons";
import type { ChatMessage } from "./types";

export interface QuickPrompt {
	label: string;
	value: string;
}

export interface ChatPanelProps {
	initialMessages?: ChatMessage[];
	placeholder?: string;
	quickPrompts?: QuickPrompt[];
	onSend?: (message: string) => void;
}

interface RenderableMessage extends ChatMessage {
	id: string;
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
	initialMessages = [],
	placeholder = DEFAULT_PLACEHOLDER,
	quickPrompts = DEFAULT_QUICK_PROMPTS,
	onSend,
}: ChatPanelProps) {
	const sessionId = useId();
	const [value, setValue] = useState("");
	const [messages, setMessages] = useState<RenderableMessage[]>(() =>
		initialMessages.map((message, index) => ({
			...message,
			id: `${sessionId}-seed-${index}`,
		})),
	);
	const nextLocalId = useRef(0);
	const transcriptRef = useRef<HTMLDivElement | null>(null);

	// biome-ignore lint/correctness/useExhaustiveDependencies: scroll-to-bottom must re-run whenever the transcript grows, even though the effect body only touches the ref.
	useEffect(() => {
		const node = transcriptRef.current;
		if (node) {
			node.scrollTop = node.scrollHeight;
		}
	}, [messages]);

	const send = () => {
		const trimmed = value.trim();
		if (!trimmed) return;
		const id = `${sessionId}-local-${nextLocalId.current++}`;
		setMessages((current) => [...current, { id, who: "user", text: trimmed }]);
		setValue("");
		onSend?.(trimmed);
	};

	return (
		<div className="tfl-chat-stack">
			<section className="tfl-card tfl-chat-card">
				<div className="tfl-chat-card-h">
					<h4>Ask the Monitor</h4>
					<span className="meta">GPT · context · TfL</span>
				</div>
				<div
					className="tfl-chat-transcript"
					ref={transcriptRef}
					aria-live="polite"
				>
					{messages.map((message) => (
						<div key={message.id} className={`tfl-msg tfl-msg-${message.who}`}>
							{message.who === "bot" && (
								<span className="tfl-msg-avatar" aria-hidden />
							)}
							<span className="tfl-msg-bubble">{message.text}</span>
						</div>
					))}
				</div>
			</section>
			<div className="tfl-chatbox">
				<textarea
					className="tfl-chatbox-ta"
					placeholder={placeholder}
					value={value}
					onChange={(e) => setValue(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === "Enter" && !e.shiftKey) {
							e.preventDefault();
							send();
						}
					}}
					rows={2}
				/>
				<div className="tfl-chatbox-row">
					<div className="tfl-chatbox-l">
						{quickPrompts.map((prompt) => (
							<button
								key={prompt.label}
								type="button"
								className="tfl-chip-sm"
								onClick={() => setValue(prompt.value)}
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
						>
							<Icon d={AUDIO_PATH} size={16} />
						</button>
						<button
							type="button"
							className="tfl-chatbox-send"
							aria-label="Send"
							onClick={send}
						>
							<Icon d={SEND_PATH} size={16} />
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}
