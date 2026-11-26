// E2E of finding outcomes (#150): open a live loop, record "fixed" and a deferral on its finding,
// check the request the browser sends and axe-check the panel. The live API is mocked so the
// spec does not depend on a running runtime service. Runs in English.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_stiction_seed42";
const SINCE = "2026-01-01T00:00:00+00:00";
const LOOP = { id: "fic101", name: "FIC-101", type: "flow", job: "j1", job_status: "idle",
  last_run_utc: new Date().toISOString(), fresh: true, kpi: { saturation_fraction: 0.4 },
  findings: [{ code: "saturated", since_utc: SINCE }] };

test.use({ locale: "en-US" });

/** Serves the live worklist and records every outcome PUT the page sends. */
async function mockLive(page: Page): Promise<Record<string, unknown>[]> {
  const puts: Record<string, unknown>[] = [];
  await page.route("**/api/live/**", (route) => {
    const request = route.request();
    if (request.method() === "PUT") {
      puts.push(request.postDataJSON() as Record<string, unknown>);
      return route.fulfill({ json: { outcome: puts.at(-1)?.outcome, actor: "e2e", at_utc: SINCE } });
    }
    const detail = new URL(request.url()).pathname.endsWith("/fic101");
    return route.fulfill({ json: detail ? { ...LOOP, history: [] } : { loops: [LOOP] } });
  });
  return puts;
}

test("finding outcomes: fixed and deferred are sent for the exact finding, axe clean", async ({ page }) => {
  const puts = await mockLive(page);
  await page.goto(`/#/d/${DATASET}/loops`);
  await page.getByRole("button", { name: "FIC-101" }).click();
  const panel = page.getByRole("group", { name: /Outcome of finding saturated/ });
  await expect(panel).toBeVisible();

  await panel.getByRole("button", { name: "Fixed" }).click();
  await expect(page.getByText(/Saved: Fixed/)).toBeVisible();
  expect(puts[0]).toEqual({ since_utc: SINCE, outcome: "fixed" });

  await expect(panel.getByRole("button", { name: "Defer", exact: true })).toBeDisabled();
  await panel.getByLabel("Defer until").fill("2999-01-02");
  await panel.getByRole("button", { name: "Defer", exact: true }).click();
  await expect(page.getByText(/Saved: Defer/)).toBeVisible();
  expect(puts[1]).toMatchObject({ since_utc: SINCE, outcome: "deferred" });
  expect(String(puts[1].until_utc)).toMatch(/^2999-01-0[23]T/);

  const results = await new AxeBuilder({ page }).analyze();
  // Like the other specs: serious and critical only (best-practice rules such as h1 are not gated).
  expect(results.violations.filter((item) => item.impact === "serious" || item.impact === "critical")
    .map((item) => item.id)).toEqual([]);
});
