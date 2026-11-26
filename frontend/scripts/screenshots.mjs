// Regenerate README screenshots against a running stack seeded with demo data.
//   docker compose up -d --wait && docker compose run --rm seed
//   cd frontend && node scripts/screenshots.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.WEB_URL ?? "http://localhost:3000";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "screenshots");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
const page = await context.newPage();
const shot = async (name) => {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600); // let charts finish their entry animation
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  console.log(`saved ${name}.png`);
};

await page.goto(`${BASE}/login`);
await page.getByLabel("Email").fill("demo@documind.dev");
await page.getByLabel("Password").fill("demo-password-123");
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForURL(/\/chat/);
const workspaceUrl = page.url().replace(/\/chat.*$/, "");

// 1. Chat: streamed answer with inline citations and the source preview panel.
await page.getByLabel("Ask a question").fill("How many days of paid time off do full-time employees get?");
await page.getByRole("button", { name: "Send" }).click();
await page.getByRole("button", { name: "Helpful answer", exact: true }).first().waitFor();
await page.getByRole("button", { name: /^Source 1:/ }).first().click();
await page.getByTestId("source-text").waitFor();
await shot("chat-citations");

// 2. Follow-up question rewritten into a standalone query.
await page.getByLabel("Ask a question").fill("and how many of those can I carry over?");
await page.getByRole("button", { name: "Send" }).click();
await page.getByRole("button", { name: "Helpful answer", exact: true }).nth(1).waitFor();
await page.getByRole("button", { name: "Close source preview" }).click();
await shot("chat-follow-up");

// 3. Document library.
await page.goto(`${workspaceUrl}/documents`);
await page.getByRole("row", { name: /Security Policy/ }).waitFor();
await shot("documents");

// 4. Evaluation dashboard.
await page.goto(`${workspaceUrl}/eval`);
await page.getByText("Metrics by run").waitFor();
await page.getByText("Faithfulness").first().waitFor();
await shot("evaluation");

// 5. Analytics.
await page.goto(`${workspaceUrl}/analytics`);
await page.getByText("Queries per day").waitFor();
await shot("analytics");

// 6. Dark mode chat.
await page.emulateMedia({ colorScheme: "dark" });
await page.goto(`${workspaceUrl}/chat`);
await page.getByRole("link", { name: "Product pricing" }).click();
await page.getByTestId("answer").first().waitFor();
await shot("chat-dark");

await browser.close();
