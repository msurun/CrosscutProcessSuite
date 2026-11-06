// Playwright end-to-end tests for the Gateway view: the not-running state, no horizontal scroll, axe checks.
// The API answers 503 for /gateway/* here (no gateway process), so the error notice is the expected state.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/gateway`;

test("gateway page shows the not-running state", async ({ page }) => {
  await page.goto(PAGE_URL);
  await expect(
    page
      .locator('nav.view-tabs button[aria-current="page"]')
      .filter({ hasText: /Gateway|Brama zapisu|Pasarela/ })
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("gateway-error")).toBeVisible({ timeout: 30_000 });
});

for (const width of [1440, 390] as const) {
  test(`gateway page has no axe violations and no horizontal scroll @${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(PAGE_URL);
    await expect(page.getByTestId("gateway-error")).toBeVisible({
      timeout: 30_000,
    });

    if (width === 390) {
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth
      );
      expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    }

    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical"
    );
    expect(
      bad.map(
        (v) =>
          `${v.id}: ${v.nodes
            .slice(0, 3)
            .map((n) => n.target.join(" "))
            .join(" | ")}`
      )
    ).toEqual([]);
  });
}

test("policy section is collapsed, opens on demand and has no axe violations", async ({ page }) => {
  await page.goto(PAGE_URL);
  const toggle = page.getByTestId("gateway-policy-toggle");
  await expect(toggle).toBeVisible({ timeout: 30_000 });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("policy-panel")).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  // No gateway process here, so the panel shows its error banner instead of a policy.
  await expect(page.getByTestId("policy-server-error")).toBeVisible({ timeout: 30_000 });

  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
});
