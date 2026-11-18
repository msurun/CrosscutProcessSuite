// Exercise the alignment panel in a browser with synthetic scan responses.
// API stubs isolate the user flow; numerical recovery is tested in the Python package.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "alignment-synthetic";
const SENSOR = "synthetic_sensor";
const SCAN = { best_delay_s: 120, interval_low_s: 60, interval_high_s: 180, method: "bootstrap", profile: [{ delay_s: 60, correlation: 0.7 }, { delay_s: 120, correlation: 0.98 }] };

/** Supply only the catalogue and stored state needed to open the soft-sensor page. */
async function stubAlignmentApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const answers: Record<string, unknown> = {
      "/api/auth/config": { auth_enabled: false, initialised: true },
      "/api/datasets": [{ id: DATASET, source: {}, time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-02T00:00:00Z" }, n_tags: 1, n_samples: 100 }],
      "/api/softsensor": [SENSOR],
      [`/api/softsensor/${SENSOR}`]: { schema_version: "1.0.0", id: SENSOR, target_tag: "lab", input_tags: ["process"], mode: "advisory" },
      [`/api/softsensor/${SENSOR}/lab`]: { count: 20, first_s: 0, last_s: 3600, rows: [] },
      [`/api/datasets/${DATASET}/softsensor/${SENSOR}/alignment-scan`]: SCAN,
    };
    if (path.endsWith("/model")) return route.fulfill({ status: 404, json: { detail: "model not fitted" } });
    await route.fulfill({ json: answers[path] ?? [] });
  });
}

test("scan displays the uncertainty and correlation profile accessibly", async ({ page }) => {
  await stubAlignmentApi(page);
  await page.goto(`/#/d/${DATASET}/softsensor`);
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
