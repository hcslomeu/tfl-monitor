"use client";

import { Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
	SheetTrigger,
} from "@/components/ui/sheet";

export function AboutSheet() {
	return (
		<Sheet>
			<SheetTrigger asChild>
				<Button variant="ghost" size="sm" aria-label="About this project">
					<Info className="size-4" />
					<span>About</span>
				</Button>
			</SheetTrigger>
			<SheetContent>
				<SheetHeader>
					<SheetTitle>tfl-monitor</SheetTitle>
					<SheetDescription>
						Live London transport status, planned works, and an agent that
						answers questions over TfL data and strategy documents.
					</SheetDescription>
				</SheetHeader>
				<div className="mt-6 space-y-3 text-sm">
					<p>
						Pipeline: TfL public APIs → Redpanda → Postgres (dbt) → FastAPI →
						this UI. Chat agent uses LangGraph with tool calls into the
						warehouse and a Pinecone vector store over TfL strategy PDFs.
					</p>
					<p>
						<a
							className="underline underline-offset-4"
							href="https://github.com/hcslomeu/tfl-monitor"
							target="_blank"
							rel="noopener noreferrer"
						>
							Source on GitHub →
						</a>
					</p>
				</div>
			</SheetContent>
		</Sheet>
	);
}
