import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";

export default function Home() {
	return (
		<main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 py-24">
			<Card className="w-full">
				<CardHeader>
					<CardTitle>Network Now</CardTitle>
					<CardDescription>
						Live line status across the TfL network.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<p className="text-sm text-muted-foreground">
						Real implementation lands in TM-E1. This scaffold only verifies that
						the Next.js app builds and the shadcn primitives render.
					</p>
				</CardContent>
			</Card>
		</main>
	);
}
