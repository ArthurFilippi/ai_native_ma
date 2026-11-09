// Optional browser check of "clicks to verify": ask, click one citation, see the highlighted span.
// Playwright is deliberately not a dependency. To run it:
//   npm i --no-save playwright && npx playwright install chromium
//   npm run build && npm start &     (mock mode, port 3000)
//   npm run e2e
import { chromium } from "playwright";

const url = process.env.WEB_URL ?? "http://localhost:3000";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
let passageRequests = 0;
page.on("request", (request) => {
  if (request.url().includes("/passages/")) passageRequests += 1;
});

await page.goto(url);
await page.getByLabel("Question about this deal").fill("What was FY2024 revenue?");
await page.getByRole("button", { name: "Ask", exact: true }).click();
await page.getByTestId("answer").waitFor();

const citation = page.locator("#claim-c1 button.citation").first();
await citation.click();
const mark = page.getByTestId("evidence-highlight");
await mark.waitFor({ state: "visible" });

const markText = (await mark.textContent()) ?? "";
const inViewport = await mark.evaluate((el) => {
  const mark = el.getBoundingClientRect();
  const panel = el.closest(".page-text")?.getBoundingClientRect();
  return mark.top >= 0 && mark.bottom <= window.innerHeight && !!panel && mark.top >= panel.top && mark.bottom <= panel.bottom;
});
console.log(JSON.stringify({ markText, inViewport, passageRequests }));
if (!markText.startsWith("Net revenue for FY2024") || !inViewport) {
  throw new Error("the highlighted span is not the cited quote or is not in view");
}
await page.screenshot({ path: process.env.SHOT ?? "one-click.png" });
await browser.close();
