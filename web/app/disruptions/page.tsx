import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";

export default function DisruptionsPage() {
	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 py-24">
			<Card className="w-full">
				<CardHeader>
					<CardTitle>Disruption Log</CardTitle>
					<CardDescription>
						Current and recent disruptions across the network.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<p className="text-sm text-muted-foreground">Coming in TM-E2.</p>
				</CardContent>
			</Card>
		</main>
	);
}
