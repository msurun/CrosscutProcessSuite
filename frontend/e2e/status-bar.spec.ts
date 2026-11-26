// Playwright end-to-end test of the global status bar (#174). The four read-only APIs it polls are
// mocked with page.route (fixture answers, no gateway stack): values on a page, a click on the
// waiting count opens the approval queue, a failed source shows "unavailable" without breaking the page,
// and axe finds no serious or critical violation at 1440 and 390 px.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const json = (route: Route, status: number, body: unknown) => route.fulfill({ status, json: body });

/** Mocks the status sources; `gatewayStatus` lets a test make the gateway fail. */
async function mockSources(page: Page, gatewayStatus = 200): Promise<void> {
  const gateway = { mode: "confirm", targets: { "FIC1.SP": "enabled" }, pending: 2 };
  await page.route(/\/api\/gateway\/status$/, (r) =>
    json(r, gatewayStatus, gatewayStatus === 200 ? gateway : { detail: "down" }));
  await page.route(/\/api\/runtime\/status$/, (r) =>
    json(r, 200, { service: { running: true, updated_at_utc: null }, jobs: [] }));
  await page.route(/\/api\/live\/loops$/, (r) => json(r, 200, { loops: [] }));
  await page.route(/\/api\/equipment\/anomalies$/, (r) => json(r, 200, []));
}

async function expectNoSeriousAxe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).include("[data-testid=status-bar]").analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad, JSON.stringify(bad.map((v) => v.id))).toEqual([]);
}

for (const width of [1440, 390]) {
  test(`status bar shows values, opens the queue and passes axe @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockSources(page);
    await page.goto("/#/controllers");
    const bar = page.getByTestId("status-bar");
    await expect(bar.getByTestId("status-bar-queue")).toContainText("2");
    await expect(bar.getByTestId("status-bar-runtime")).toBeVisible();
    await expectNoSeriousAxe(page);
    await bar.getByTestId("status-bar-queue").getByRole("button").click();
    await expect(page).toHaveURL(/gateway/);
  });
}

test("a failed source shows unavailable and the page still works", async ({ page }) => {
  await mockSources(page, 500);
  await page.goto("/#/controllers");
  await expect(page.getByTestId("status-bar-mode")).toContainText(/Unavailable|Niedostępne|No disponible/);
  await expect(page.getByTestId("status-bar-runtime")).toBeVisible();
});
