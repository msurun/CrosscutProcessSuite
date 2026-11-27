// Browser test of the soft sensor bias correction settings (Polish UI): save the bundled example plus
// a bias_correction block through the real API, open the page and read the summary line and the
// advanced section of the editor. Also axe (serious/critical none) at 1440 and 390 px.
// Needs the demo dataset and E2E_DATA_ROOT exactly like e2e/softsensor.spec.ts.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/softsensor`;
const EXAMPLE = fileURLToPath(new URL("../../softsensor/examples/mill_circuit_pls.json", import.meta.url));
const BIAS = { weight: 0.5, k_sigma: 2.5, consecutive: 4 };

/** The data root served by the API under test. */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.describe.configure({ mode: "serial" });
test.beforeEach(() => rmSync(join(dataRoot(), "_softsensor"), { recursive: true, force: true }));
test.setTimeout(120_000);

/** Saves the example with a bias_correction block through the API and opens the page. */
async function openWithBias(page: Page): Promise<void> {
  const example = JSON.parse(readFileSync(EXAMPLE, "utf-8")) as Record<string, unknown>;
  const saved = await page.request.put(`/api/softsensor/${String(example.id)}`, {
    data: { ...example, bias_correction: BIAS },
  });
  expect(saved.ok()).toBeTruthy();
  await page.goto(PAGE_URL);
  await expect(page.getByLabel("Czujnik programowy")).toBeVisible({ timeout: 30_000 });
}

test("the summary and the editor show the bias correction settings", async ({ page }) => {
  await openWithBias(page);
  await expect(page.getByText("waga EWMA 0.5, próg 2.5 sigma, dryf po 4 z rzędu")).toBeVisible();
  await expect(page.getByTestId("soft-bias-hint")).toContainText("nie dowodzi");
  await expect(page.getByTestId("schema-object-bias_correction")).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`bias correction section has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openWithBias(page);
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
