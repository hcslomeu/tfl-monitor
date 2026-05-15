import {
	GithubIcon,
	LinkedinIcon,
	UpworkIcon,
	XIcon,
} from "@/components/icons";

const socials = [
	{ label: "Github", href: "https://github.com/hcslomeu", Icon: GithubIcon },
	{
		label: "LinkedIn",
		href: "https://www.linkedin.com/in/humbertolomeu/",
		Icon: LinkedinIcon,
	},
	{ label: "X", href: "https://x.com/hcslomeu", Icon: XIcon },
	{
		label: "Upwork",
		href: "https://upwork.com/freelancers/humbertolomeu",
		Icon: (props: { size?: number }) => <UpworkIcon monochrome {...props} />,
	},
];

export function Footer() {
	return (
		<footer className="hl-footer">
			<div className="hl-footer-inner">
				<div className="hl-footer-foot">
					<a
						className="hl-footer-mark"
						href="https://retrieverworks.com"
						target="_blank"
						rel="noopener noreferrer"
						aria-label="Retrieverworks"
					>
						<span className="hl-footer-mark-logo">
							{/* eslint-disable-next-line @next/next/no-img-element */}
							{/* biome-ignore lint/performance/noImgElement: SVG wordmark — next/image adds no value here */}
							<img src="/brand/retrieverworks-wordmark.svg" alt="" />
						</span>
						<span className="hl-footer-mark-tagline">
							When you see this mark, I built it.
						</span>
					</a>
					{/* biome-ignore lint/a11y/useSemanticElements: visual pill, not a form group — fieldset would inject a legend baseline */}
					<div
						className="hl-footer-socials"
						role="group"
						aria-label="Social links"
					>
						{socials.map(({ label, href, Icon }) => (
							<a
								key={label}
								aria-label={label}
								href={href}
								target="_blank"
								rel="noreferrer"
							>
								<Icon size={16} />
							</a>
						))}
					</div>
				</div>
			</div>
		</footer>
	);
}
