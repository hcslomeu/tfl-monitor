import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";

export default function ReliabilityPage() {
	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 py-24">
			<Card className="w-full">
				<CardHeader>
					<CardTitle>Reliability</CardTitle>
					<CardDescription>
						Per-line reliability scored over a rolling window.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<p className="text-sm text-muted-foreground">Coming in TM-E1.</p>
				</CardContent>
			</Card>
		</main>
	);
}
