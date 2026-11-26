import { expect, test } from "@playwright/test";

const POLICY = `# Travel Policy

## Per Diem
The daily meal allowance for business travel is 75 EUR. Hotel bookings must be made through the
travel portal at least 7 days before departure.

## Approvals
Trips longer than five days require written approval from a department head.
`;

test("register → upload → ask → cited answer → source preview", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/w\/[^/]+\/chat/);

  await page.getByRole("link", { name: "Documents" }).click();
  await page.getByTestId("file-input").setInputFiles({
    name: "travel-policy.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(POLICY),
  });
  const row = page.getByRole("row", { name: /travel-policy/i });
  await expect(row.getByText("Ready")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "Chat" }).click();
  await page.getByLabel("Ask a question").fill("What is the daily meal allowance for business travel?");
  await page.getByRole("button", { name: "Send" }).click();

  const answer = page.getByTestId("answer").last();
  await expect(answer).toContainText("75 EUR");
  // Feedback buttons only render on the persisted message, i.e. once streaming has finished.
  await expect(page.getByRole("button", { name: "Helpful answer", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: /^Source 1:/ }).first().click();
  await expect(page.getByTestId("source-text")).toContainText("75 EUR");

  // Guardrail: unrelated question is refused instead of hallucinated.
  await page.getByLabel("Ask a question").fill("Who painted the Mona Lisa?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Not enough context")).toBeVisible();
  await expect(page.getByRole("button", { name: "Helpful answer", exact: true })).toHaveCount(2);

  await page.getByRole("button", { name: "Helpful answer", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Helpful answer", exact: true }).first()).toHaveAttribute("aria-pressed", "true");
});
