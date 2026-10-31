// Browser test of the Dataset Readiness & Onboarding view (Phase 1, #39):
// navigates to the onboarding view, verifies traffic lights, module cards,
// and runs axe-core accessibility checks at 1440 and 390 px with no horizontal scroll.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/onboarding`;

async function openOnboardingPage(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("onboarding-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: /Wdrożenie|Onboarding|Incorporación/ })).toHaveAttribute("aria-current", "page");
}

test("renders onboarding view with overall verdict and module checklist", async ({ page }) => {
  const errors: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });

  await openOnboardingPage(page);

  await expect(page.getByTestId("onboarding-overall-verdict")).toBeVisible();
  await expect(page.getByTestId("onboarding-module-loops")).toBeVisible();
  await expect(page.getByTestId("onboarding-module-anomaly")).toBeVisible();
  await expect(page.getByTestId("onboarding-module-softsensor")).toBeVisible();

  expect(errors).toEqual([]);
});

test("navigating via view tabs reaches onboarding view", async ({ page }) => {
  await page.goto(`/#/d/${DATASET}/trends`);
  const onboardingTab = page.locator("nav.view-tabs").getByRole("button", { name: /Wdrożenie|Onboarding|Incorporación/ });
  await expect(onboardingTab).toBeVisible();
  await onboardingTab.click();

  await expect(onboardingTab).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("onboarding-page")).toBeVisible({ timeout: 30_000 });
});

for (const width of [1440, 390]) {
  test(`onboarding page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openOnboardingPage(page);
    await page.waitForLoadState("networkidle");
    if (width === 390) {
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    }
    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}

