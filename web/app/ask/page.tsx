import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";

export default function AskPage() {
	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 py-24">
			<Card className="w-full">
				<CardHeader>
					<CardTitle>Ask</CardTitle>
					<CardDescription>
						Conversational agent with SQL + RAG tools.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<p className="text-sm text-muted-foreground">Coming in TM-E3.</p>
				</CardContent>
			</Card>
		</main>
	);
}
