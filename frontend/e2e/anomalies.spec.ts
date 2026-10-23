// Browser test of the Anomalies page (Polish): load the example config, fit on the first hours of
// the simulated mill circuit, scan, see the charts and the events table (or the "no events"
// message). Also axe (serious/critical none) at 1440 and 390 px and no horizontal scroll at 390.
// Needs the demo dataset `mill_circuit_observational_seed42`; the API writes to its data root
// (_anomaly), so use a scratch copy and pass its path in E2E_DATA_ROOT: before each test the spec
// deletes the _anomaly folder there, so every test is independent and the suite can be re-run.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { rmSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const URL = `/#/d/${DATASET}/anomalies`;

/** Deletes the stored anomaly configs, models and manifests under the API's data root. */
function resetAnomalyState(): void {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  rmSync(join(root, "_anomaly"), { recursive: true, force: true });
}

test.beforeEach(resetAnomalyState);
// Fit and scan read the whole record; under load (two workers) that can take a while.
test.setTimeout(120_000);

/** Opens the page, loads the example, fits on the default first hours and scans the whole record. */
async function loadFitAndScan(page: Page): Promise<void> {
  await page.goto(URL);
  await page.getByRole("button", { name: "Wczytaj przykład" }).click();
  await expect(page.getByLabel("Detektor")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("note").first()).toContainText("Tylko doradztwo");
  await page.getByRole("button", { name: "Dopasuj model" }).click();
  await expect(page.getByRole("heading", { name: "Model", exact: true })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Skanuj", exact: true }).click();
  await expect(page.getByTestId("anomaly-result")).toBeVisible({ timeout: 60_000 });
}

test("load example, fit, scan and read the result", async ({ page }) => {
  await loadFitAndScan(page);
  await expect(page.getByText(/Wiersze nieużyte: \d+ nieskończonych/)).toBeVisible();
  await expect(page.getByText("nigdy nie są uzupełniane")).toBeVisible();
  await expect(page.locator(".anomaly-chart")).toHaveCount(2);
  await expect(page.locator(".anomaly-chart canvas").first()).toBeVisible();
  const table = page.getByRole("table", { name: /Liczba zdarzeń/ });
  const none = page.getByText("Brak zdarzeń w tym oknie.");
  await expect(table.or(none)).toBeVisible();
  if (await table.isVisible()) {
    await expect(page.getByRole("list", { name: "Udział w SPE" })).toBeVisible();
  }
});

for (const width of [1440, 390]) {
  test(`anomalies page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await loadFitAndScan(page);
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
