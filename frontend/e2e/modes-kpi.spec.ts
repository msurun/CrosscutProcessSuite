// E2E of operating modes in the live loop worklist (#146): the mode badge and the per-mode KPI
// table appear in the loop detail. The live API is mocked with page.route; axe-checked. English.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_stiction_seed42";
const KPI = { service_factor: 0.9, saturation_fraction: 0.1, harris_index: 0.6, classification: "ok" };
const LOOP = { id: "fic101", name: "FIC-101", type: "flow", job: "j1", job_status: "idle",
  last_run_utc: new Date().toISOString(), fresh: true, kpi: { ...KPI, mode: "normal" }, findings: [],
  mode: "normal", kpi_scope: "mode",
  by_mode: { normal: KPI, high_throughput: { ...KPI, harris_index: 0.3, classification: "poor_performance" } } };

test.use({ locale: "en-US" });

/** Serves the live worklist and one loop detail. */
async function mockLive(page: Page): Promise<void> {
  await page.route("**/api/live/**", (route) => {
    const detail = new URL(route.request().url()).pathname.endsWith("/fic101");
    return route.fulfill({ json: detail ? { ...LOOP, history: [] } : { loops: [LOOP] } });
  });
}

test("mode badge and per-mode KPI table in the loop detail, axe clean", async ({ page }) => {
  await mockLive(page);
  await page.goto(`/#/d/${DATASET}/loops`);
  await expect(page.getByText("Mode: normal").first()).toBeVisible();
  await page.getByRole("button", { name: "FIC-101" }).click();
  const table = page.getByRole("table", { name: /KPI per operating mode/ });
  await expect(table).toBeVisible();
  await expect(table.getByRole("row", { name: /high_throughput.*poor_performance/ })).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((item) => item.impact === "serious" || item.impact === "critical")
    .map((item) => item.id)).toEqual([]);
});
