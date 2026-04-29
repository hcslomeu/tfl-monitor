"use client";

/**
 * Conversational chat view for `/ask`.
 *
 * Talks to `POST /api/v1/chat/stream` via `streamChat()` and renders
 * incremental tokens, tool-use status, and final/errored states.
 */

import { type FormEvent, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { streamChat } from "@/lib/api/chat-stream";
import { ApiError } from "@/lib/api-client";

type Role = "user" | "assistant";

interface Message {
	id: string;
	role: Role;
	content: string;
	errored?: boolean;
}

export function ChatView() {
	const threadIdRef = useRef<string>(crypto.randomUUID());
	const [messages, setMessages] = useState<Message[]>([]);
	const [input, setInput] = useState("");
	const [busy, setBusy] = useState(false);
	const [agentStatus, setAgentStatus] = useState<string | null>(null);
	const [serviceError, setServiceError] = useState<string | null>(null);

	async function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		const trimmed = input.trim();
		if (!trimmed || busy) return;
		setInput("");
		setBusy(true);
		setServiceError(null);
		setAgentStatus(null);
		setMessages((prev) => [
			...prev,
			{ id: crypto.randomUUID(), role: "user", content: trimmed },
			{ id: crypto.randomUUID(), role: "assistant", content: "" },
		]);

		try {
			let assistantContent = "";
			let endedWithError = false;
			for await (const frame of streamChat({
				thread_id: threadIdRef.current,
				message: trimmed,
			})) {
				if (frame.type === "token") {
					assistantContent += frame.content;
					setAgentStatus(null);
					setMessages((prev) => {
						const next = [...prev];
						const last = next[next.length - 1];
						next[next.length - 1] = {
							...last,
							role: "assistant",
							content: assistantContent,
						};
						return next;
					});
				} else if (frame.type === "tool") {
					setAgentStatus(`Using tool: ${frame.content}…`);
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
						role: "assistant",
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
			setAgentStatus(null);
		}
	}

	return (
		<Card className="w-full">
			<CardHeader>
				<CardTitle aria-level={1} role="heading">
					Ask tfl-monitor
				</CardTitle>
				<CardDescription>
					Conversational agent over live TfL operations and strategy documents.
					Answers stream as the agent thinks.
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				{serviceError ? (
					<Alert role="alert" data-tone="destructive">
						<AlertTitle>Agent unavailable</AlertTitle>
						<AlertDescription>{serviceError}</AlertDescription>
					</Alert>
				) : null}

				{messages.length > 0 ? (
					<ul
						aria-label="Conversation"
						className="flex flex-col gap-3"
						data-testid="conversation"
					>
						{messages.map((message, index) => {
							const isLast = index === messages.length - 1;
							const showSkeleton =
								busy &&
								isLast &&
								message.role === "assistant" &&
								message.content === "";
							return (
								<li
									key={message.id}
									data-role={message.role}
									data-errored={message.errored ? "true" : undefined}
									className="flex flex-col gap-1"
								>
									<span className="text-xs font-medium uppercase text-muted-foreground">
										{message.role === "user" ? "You" : "Agent"}
									</span>
									{showSkeleton ? (
										<Skeleton className="h-4 w-32" />
									) : (
										<p className="whitespace-pre-wrap text-sm">
											{message.content}
										</p>
									)}
								</li>
							);
						})}
					</ul>
				) : null}

				{agentStatus ? (
					<p
						data-testid="agent-status"
						className="text-sm text-muted-foreground"
					>
						{agentStatus}
					</p>
				) : null}

				<form onSubmit={handleSubmit} className="flex flex-col gap-2">
					<label htmlFor="chat-input" className="sr-only">
						Message
					</label>
					<textarea
						id="chat-input"
						rows={3}
						maxLength={4000}
						value={input}
						onChange={(e) => setInput(e.target.value)}
						disabled={busy}
						placeholder="Ask about tube status, disruptions, or strategy…"
						className="w-full rounded-md border bg-transparent p-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
					/>
					<div className="flex justify-end">
						<Button type="submit" disabled={busy || !input.trim()}>
							{busy ? "Streaming…" : "Send"}
						</Button>
					</div>
				</form>
			</CardContent>
		</Card>
	);
}
