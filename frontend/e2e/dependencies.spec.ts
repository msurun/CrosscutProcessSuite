// Playwright test of the Dependencies view (#166). The API answers are mocked with page.route: a stale
// anomaly model (needs relearn) and a stale job are listed with their reasons, a re-confirmation sends the
// required note and the row disappears, and the view has no serious axe violations at 1440 and 390 px and
// no horizontal scroll. English locale, auth off.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/dependencies`;
const LIST_URL = /\/api\/dependencies$/;
const CONFIRM_URL = /\/api\/dependencies\/confirm$/;

test.use({ locale: "en-US" });

const MODEL = {
  key: "anomaly:m1", kind: "anomaly", id: "m1", built_on_version: 1, stale_since_version: 2,
  needs_relearn: true, actions: ["relearn", "reconfirm"],
  reasons: [{ tag: "CR1.CSS.PV", kind: "remapped", detail: "sim:ns=2;s=A -> sim:ns=2;s=B" }],
};
const JOB = {
  key: "job:kpi", kind: "job", id: "kpi", built_on_version: 1, stale_since_version: 2,
  needs_relearn: false, actions: ["edit_config", "reconfirm"],
  reasons: [{ tag: "CR1.CSS.SP", kind: "removed", detail: "tag removed from catalogue" }],
};

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, confirmed: { body: unknown }) {
  let items = [MODEL, JOB];
  await page.route(LIST_URL, (route) => json(route, 200, { published_version: 2, tracked: 5, items }));
  await page.route(CONFIRM_URL, (route) => {
    confirmed.body = route.request().postDataJSON();
    items = items.filter((i) => i.key !== (confirmed.body as { key: string }).key);
    return json(route, 200, { key: "anomaly:m1", confirmed: { by: "eng1" } });
  });
}

test("stale items are listed with reasons and actions", async ({ page }) => {
  await mockApi(page, { body: null });
  await page.goto(PAGE_URL);
  const model = page.getByTestId("dependency-anomaly:m1");
  await expect(model).toBeVisible({ timeout: 30_000 });
  await expect(model).toContainText("CR1.CSS.PV");
  await expect(model).toContainText("source address changed");
  await expect(model).toContainText("Needs relearn");
  await expect(page.getByTestId("dependency-job:kpi")).toContainText("tag removed");
  await expect(page.getByTestId("dependency-job:kpi")).toContainText("Edit the config");
});

test("re-confirm needs a note and removes the row", async ({ page }) => {
  const confirmed: { body: unknown } = { body: null };
  await mockApi(page, confirmed);
  await page.goto(PAGE_URL);
  const row = page.getByTestId("dependency-anomaly:m1");
  await expect(row).toBeVisible({ timeout: 30_000 });
  const button = row.getByRole("button", { name: "Re-confirm" });
  await expect(button).toBeDisabled();
  await row.getByLabel("Why the change is acceptable").fill("address moved, same signal");
  await button.click();
  await expect(page.getByTestId("dependency-anomaly:m1")).toHaveCount(0);
  expect(confirmed.body).toEqual({ key: "anomaly:m1", note: "address moved, same signal" });
  await expect(page.getByRole("status").filter({ hasText: "re-confirmed" })).toBeVisible();
});

for (const width of [1440, 390] as const) {
  test(`dependencies view has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page, { body: null });
    await page.goto(PAGE_URL);
    await expect(page.getByTestId("dependency-anomaly:m1")).toBeVisible({ timeout: 30_000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}
