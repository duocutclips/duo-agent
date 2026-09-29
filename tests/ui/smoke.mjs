// UI smoke test: opens every page of the built frontend against a running backend and fails on
// error banners, console errors or missing content. Usage:
//   node tests/ui/smoke.mjs [baseUrl] [screenshotDir]
// Needs: backend on 127.0.0.1:8765 (with the demo campaign), `vite preview` on :4173,
// and a Chromium (CHROMIUM_PATH, default /opt/pw-browsers/chromium).
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(new URL("../../apps/desktop/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const base = process.argv[2] ?? "http://127.0.0.1:4173";
const shots = process.argv[3];
if (shots) mkdirSync(shots, { recursive: true });

const PAGES = [
  ["dashboard", "Dashboard", "Recent projects"],
  ["campaigns", "Campaigns", "Seed Heist"],
  ["media", "Media", "gameplay_a"],
  ["ideas", "Ideas", "Novelty"],
  ["scripts", "Scripts", "Estimated speaking time"],
  ["voice", "Voice", "Offline system voice"],
  ["projects", "Projects", "Videos"],
  ["templates", "Templates", "Story"],
  ["exports", "Exports", "Exported videos"],
  ["submissions", "Submissions", "Add a post"],
  ["analytics", "Analytics", "By hook"],
  ["settings", "Settings", "Integrations"],
];

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? "/opt/pw-browsers/chromium", args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()} @ ${m.location().url}`));
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

async function check(route, heading, text) {
  await page.goto(`${base}/#/${route}`);
  await page.getByRole("heading", { level: 1, name: heading }).waitFor({ timeout: 10_000 });
  await page.getByText(text, { exact: false }).first().waitFor({ timeout: 10_000 });
  const errors = await page.locator(".banner-error").allTextContents();
  if (errors.length) problems.push(`${route}: error banner: ${errors.join(" | ")}`);
  if (shots) await page.screenshot({ path: path.join(shots, `${route}.png`), fullPage: true });
  console.log(`ok  ${route}`);
}

try {
  await page.goto(base);
  await page.getByTestId("backend-status").getByText("connected").waitFor({ timeout: 15_000 });
  for (const [route, heading, text] of PAGES) await check(route, heading, text);

  // Project detail: open the first project and walk every tab.
  await page.goto(`${base}/#/projects`);
  const first = page.locator("table a").first();
  await first.waitFor({ timeout: 10_000 });
  await first.click();
  await page.locator(".stepper").waitFor();
  for (const tab of ["Script", "Voice", "Footage & style", "Timeline", "Preview & QA", "Export & publish", "History"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(400);
    const errors = await page.locator(".banner-error").allTextContents();
    if (errors.length) problems.push(`project/${tab}: error banner: ${errors.join(" | ")}`);
    if (shots) await page.screenshot({ path: path.join(shots, `project-${tab.split(" ")[0].toLowerCase()}.png`), fullPage: true });
    console.log(`ok  project tab ${tab}`);
  }
  await page.getByRole("tab", { name: "Preview & QA" }).click();
  await page.getByText("Quality check").waitFor();
  const qa = await page.locator("td.qa-pass, td.qa-fail").count();
  if (qa === 0) problems.push("project: QA table is empty");
} catch (e) {
  problems.push(`exception: ${e.message}`);
} finally {
  await browser.close();
}

if (problems.length) {
  console.error("UI smoke test FAILED:\n" + problems.map((p) => "  - " + p).join("\n"));
  process.exit(1);
}
console.log("UI smoke test passed.");
