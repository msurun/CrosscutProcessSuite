// Exercise the alignment panel in a browser with a stubbed scan response on the real stack.
// Numerical recovery of the delay is tested in the Python package.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { rmSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const SCAN = { best_delay_s: 120, interval_low_s: 60, interval_high_s: 180, method: "bootstrap", profile: [{ delay_s: 60, correlation: 0.7 }, { delay_s: 120, correlation: 0.98 }] };

/** The data root served by the API under test (the page stores sensors there). */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

// Soft sensor state is shared on disk, so run serially and start from an empty store.
test.describe.configure({ mode: "serial" });
test.beforeEach(() => rmSync(join(dataRoot(), "_softsensor"), { recursive: true, force: true }));

/** Stub only the scan response; the page, sensor and catalogue come from the real stack. */
async function stubScan(page: Page): Promise<void> {
  await page.route("**/alignment-scan", (route) => route.fulfill({ json: SCAN }));
}

test("scan displays the uncertainty and correlation profile accessibly", async ({ page }) => {
  await stubScan(page);
  await page.goto(`/#/d/${DATASET}/softsensor`);
  await page.getByRole("button", { name: "Wczytaj przykład" }).click();
  await page.getByLabel("Tag odniesienia", { exact: true }).fill("online.quality");
  const response = page.waitForRequest((request) => request.url().endsWith("/alignment-scan"));
  await page.getByRole("button", { name: "Skanuj opóźnienia" }).click();
  expect((await response).postDataJSON()).toEqual({ reference_tag: "online.quality", min_delay_s: -3600, max_delay_s: 3600, step_s: 60 });
  await expect(page.getByTestId("alignment-result")).toContainText("przedział niepewności: 60 do 180 s");
  await page.locator("summary").filter({ hasText: "Profil korelacji" }).click();
  await expect(page.getByRole("cell", { name: "0.980" })).toBeVisible();
  const axe = await new AxeBuilder({ page }).include('section[aria-label="Skan wyrównania opóźnienia"]').analyze();
  expect(axe.violations).toEqual([]);
});
