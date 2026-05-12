"use client";

import { MessageCircle } from "lucide-react";
import { useState } from "react";

import { ChatView } from "@/components/chat-view";
import { Button } from "@/components/ui/button";
import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
	DrawerTrigger,
} from "@/components/ui/drawer";

export function ChatPanel() {
	const [open, setOpen] = useState(false);

	return (
		<>
			<aside
				aria-label="Agent chat"
				className="hidden lg:sticky lg:top-6 lg:flex lg:h-[calc(100vh-3rem)] lg:flex-col"
			>
				<ChatView />
			</aside>

			<div className="lg:hidden">
				<Drawer open={open} onOpenChange={setOpen}>
					<DrawerTrigger asChild>
						<Button
							size="icon"
							className="fixed right-6 bottom-6 size-14 rounded-full shadow-lg"
							aria-label="Open chat"
						>
							<MessageCircle className="size-6" />
						</Button>
					</DrawerTrigger>
					<DrawerContent className="h-[60vh]">
						<DrawerHeader>
							<DrawerTitle>Ask the agent</DrawerTitle>
						</DrawerHeader>
						<div className="flex-1 overflow-hidden px-4 pb-4">
							<ChatView />
						</div>
					</DrawerContent>
				</Drawer>
			</div>
		</>
	);
}
