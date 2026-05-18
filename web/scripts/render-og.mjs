import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const INPUT = path.resolve(__dirname, "og-card.html");
const OUTPUT = path.resolve(__dirname, "..", "public", "og.png");

const browser = await chromium.launch();
const ctx = await browser.newContext({
	viewport: { width: 1200, height: 630 },
	deviceScaleFactor: 2,
});
const page = await ctx.newPage();
await page.goto(`file://${INPUT}`);
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(150);
await page.screenshot({
	path: OUTPUT,
	type: "png",
	omitBackground: false,
	clip: { x: 0, y: 0, width: 1200, height: 630 },
});
await browser.close();
console.log("wrote", OUTPUT);
