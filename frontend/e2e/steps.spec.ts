// Browser test of the Steps analyser page (Polish): pick the mill_feed loop on the demo dataset
// mill_circuit_step_test_seed42, run the analysis, find an OUT step judged OK, open its step chart,
// and check the nav tab, axe (serious/critical none) at 1440 and 390 px and no horizontal scroll.
// The API only reads the dataset, so no data root override is needed; the spec fails on any HTTP
// response with status 400 or more.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_step_test_seed42";
const PAGE_URL = `/#/d/${DATASET}/steps`;
// The analysis fits every step of the loop; under load (two workers) that can take a while.
const ANALYSIS_TIMEOUT_MS = 90_000;

// Polish texts the user sees (see .agent-out/steps_pl.json).
const TITLE_TEXT = "Analizator kroków";
const LOOP_LABEL = "Pętla";
const RUN_BUTTON_TEXT = "Uruchom analizę";
const OUT_STEP_TEXT = "Krok OUT (tryb ręczny)";
const VERDICT_OK_TEXT = "OK";
const NAV_TAB_TEXT = "Kroki";
const TARGET_LOOP = "mill_feed";

/** Opens the Steps page and waits for the view heading. */
async function openStepsPage(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await expect(page.getByRole("heading", { name: TITLE_TEXT })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: NAV_TAB_TEXT })).toHaveAttribute("aria-current", "page");
}

/** Chooses the target loop and runs the analysis, waiting for the first OUT step row. */
async function runAnalysisForTargetLoop(page: Page): Promise<void> {
  await page.getByLabel(LOOP_LABEL, { exact: true }).selectOption(TARGET_LOOP);
  await page.getByRole("button", { name: RUN_BUTTON_TEXT }).click();
  const resultsTable = page.locator("table.steps-table");
  await expect(resultsTable).toContainText(OUT_STEP_TEXT, { timeout: ANALYSIS_TIMEOUT_MS });
  await expect(resultsTable).toContainText(VERDICT_OK_TEXT, { timeout: ANALYSIS_TIMEOUT_MS });
}

test("run the mill_feed analysis, see an OK OUT step and open its chart", async ({ page }) => {
  const errors: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });

  await openStepsPage(page);
  await runAnalysisForTargetLoop(page);

  const okStepRow = page.getByRole("row").filter({ hasText: OUT_STEP_TEXT }).filter({ hasText: VERDICT_OK_TEXT });
  await okStepRow.first().getByRole("button").first().click();

  await expect(page.getByTestId("step-chart")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("step-chart").locator("canvas").first()).toBeVisible();
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) {
  test(`steps page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStepsPage(page);
    await runAnalysisForTargetLoop(page);
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
