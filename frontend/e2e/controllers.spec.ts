// Playwright end-to-end tests for the Controllers view (Phase 2.5, step 7). The API answers are
// mocked with page.route (no controller host here): the list and the detail with variables, the
// On / Off calls, a 422 refusal of operator limits, the tab, no horizontal scroll at 390 px and
// axe at 1440 and 390 px. The route is "#/controllers", outside the dataset path.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const PAGE_URL = "/#/controllers";
const LIST_URL = /\/api\/controllers$/;
const ONE_URL = /\/api\/controllers\/C1$/;
const COMMAND_URL = /\/api\/controllers\/C1\/command$/;
const VARIABLE_URL = /\/api\/controllers\/C1\/variables\/[^/]+$/;

const summary = {
  id: "C1",
  type: "fuzzy",
  description: "Rougher supervisor",
  cycle_s: 30,
  state: "on",
  reason: "running",
  last_cycle_utc: "2026-01-01T00:00:00+00:00",
  last_duration_s: 0.2,
  overruns: 2,
  consecutive_overruns: 1,
  liveness_utc: "2026-01-01T00:00:01+00:00",
  last_explanation: "mv1: +1 [level high and feed rising]",
  disabled: [],
};

const detail = {
  ...summary,
  variables: [
    {
      id: "mv1", role: "MV", binding: { loop: "L1" }, enabled: true,
      limits: { eng: { lo: 0, hi: 100 }, operator: { lo: 10, hi: 90 }, operator_catalogue: { lo: 10, hi: 90 } },
      status: "good", reasons: [], value: 42, sp_value: 40, source_utc: null,
    },
    {
      id: "cv1", role: "CV", binding: { tag: "t.cv" }, enabled: true,
      limits: { operator_catalogue: null },
      status: "bad", reasons: ["stale", "anomaly"], value: 4.5, sp_value: null, source_utc: null,
    },
  ],
};

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page) {
  await page.route(LIST_URL, (route) => json(route, 200, { controllers: [summary] }));
  await page.route(ONE_URL, (route) => json(route, 200, detail));
  await page.route(COMMAND_URL, (route) => json(route, 200, { accepted: true }));
}

async function expectNoSeriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`),
  ).toEqual([]);
}

async function openDetail(page: Page) {
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("controllers-list")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("controller-open-C1").click();
  await expect(page.getByTestId("controllers-detail")).toBeVisible();
}

test("the Controllers tab opens the view and shows the variables", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/d/mill_circuit_observational_seed42/trends");
  await page.locator("nav.view-tabs button").filter({ hasText: /Regulatory/ }).click();
  await expect(page).toHaveURL(/#\/controllers$/);
  await expect(page.getByTestId("controllers-page")).toBeVisible({ timeout: 30_000 });
  await openDetail(page);
  await expect(page.getByTestId("controller-var-cv1")).toContainText("4.5");
  await expect(page.getByTestId("controller-var-mv1")).toContainText("0 .. 100");
});

test("On and Off post the commands", async ({ page }) => {
  await mockApi(page);
  const sent: string[] = [];
  await page.route(COMMAND_URL, (route) => {
    sent.push(route.request().postData() ?? "");
    return json(route, 200, { accepted: true });
  });
  await openDetail(page);
  await page.getByTestId("controller-on").click();
  await page.getByTestId("controller-off").click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent.map((body) => JSON.parse(body).command)).toEqual(["switch_on", "switch_off"]);
});

test("operator limits outside the engineering range show the refusal", async ({ page }) => {
  await mockApi(page);
  await page.route(VARIABLE_URL, (route) => json(route, 422, { detail: ["operator range must lie inside engineering range 0..100"] }));
  await openDetail(page);
  await page.getByTestId("controller-hi-mv1").fill("500");
  await page.getByTestId("controller-save-mv1").click();
  await expect(page.getByTestId("controllers-error")).toContainText("inside engineering range");
});

for (const width of [1440, 390] as const) {
  test(`controllers view has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    await openDetail(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    await expectNoSeriousAxe(page);
  });
}
