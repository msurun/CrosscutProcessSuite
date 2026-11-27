// Playwright end-to-end tests for Administration > Health (#170). The API answers are mocked with
// page.route (like the status-bar and controllers specs): the items with ok / warning / error and
// their reasons, the refresh, the log export download with the chosen range, the refusal of an
// export, no horizontal scroll at 390 px and axe at 1440 and 390 px.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const PAGE_URL = "/#/d/mill_circuit_observational_seed42/health";
const HEALTH_URL = /\/api\/admin\/health$/;
const EXPORT_URL = /\/api\/admin\/logs\/export\?/;

const report = {
  generated_utc: "2026-11-26T12:00:00+00:00",
  status: "error",
  items: [
    { id: "runtime", group: "runtime", status: "ok", code: "runtime_running", reason: "The runtime is running.",
      details: { uptime_s: 7500, updated_age_s: 2 } },
    { id: "job:kpi-1", group: "jobs", status: "error", code: "job_error", reason: "The last run failed: boom.",
      details: { last_error: "boom", last_error_utc: "2026-11-26T11:59:00+00:00", last_run_utc: "2026-11-26T11:59:00+00:00",
                 overrun_count: 2, lag_s: 4 } },
    { id: "gateway", group: "gateway", status: "warning", code: "gateway_mode_off", reason: "The gateway mode is off.",
      details: { mode: "off" } },
    { id: "liveness:runtime", group: "liveness", status: "ok", code: "liveness_ok", reason: "fresh",
      details: { age_s: 3 } },
    { id: "audit", group: "audit", status: "ok", code: "audit_ok", reason: "Audit records are written.",
      details: { last_write_utc: "2026-11-26T11:58:00+00:00", age_s: 120 } },
    { id: "disk", group: "system", status: "ok", code: "disk_ok", reason: "Enough free space.",
      details: { free_bytes: 50 * 2 ** 30, total_bytes: 100 * 2 ** 30 } },
    { id: "versions", group: "system", status: "ok", code: "versions_ok", reason: "consistent",
      details: { versions: { "crosscut-api": "0.0.1", "crosscut-runtime": "0.0.1" } } },
  ],
};

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page) {
  await page.route(HEALTH_URL, (route) => json(route, 200, report));
}

async function expectNoSeriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`),
  ).toEqual([]);
}

async function openPage(page: Page) {
  await mockApi(page);
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("health-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("health-item-runtime")).toBeVisible();
}

test("shows every item with its status and reason", async ({ page }) => {
  await openPage(page);
  await expect(page.getByTestId("health-overall")).toContainText("Coś jest nie tak");
  await expect(page.getByTestId("health-item-job:kpi-1")).toContainText("Błąd");
  await expect(page.getByTestId("health-item-job:kpi-1")).toContainText("boom");
  await expect(page.getByTestId("health-item-job:kpi-1")).toContainText("Przekroczenia: 2");
  await expect(page.getByTestId("health-item-gateway")).toContainText("Ostrzeżenie");
  await expect(page.getByTestId("health-item-runtime")).toContainText("Czas pracy: 2 h 5 min");
  await expect(page.getByTestId("health-item-disk")).toContainText("50.0 / 100.0 GiB");
});

test("the Administration group offers the Health tab", async ({ page }) => {
  await openPage(page);
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: "Stan systemu" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("Refresh reads the report again", async ({ page }) => {
  await openPage(page);
  let reads = 0;
  await page.route(HEALTH_URL, (route) => {
    reads += 1;
    return json(route, 200, { ...report, status: "ok", items: report.items.slice(0, 1) });
  });
  await page.getByTestId("health-refresh").click();
  await expect.poll(() => reads).toBeGreaterThan(0);
  await expect(page.getByTestId("health-overall")).toContainText("Wszystko w porządku");
});

test("the log export downloads the zip of the chosen range", async ({ page }) => {
  await openPage(page);
  let url = "";
  await page.route(EXPORT_URL, (route) => {
    url = route.request().url();
    return route.fulfill({ status: 200, contentType: "application/zip", body: "PK" });
  });
  await page.getByTestId("health-export-start").fill("2026-11-26T10:00");
  await page.getByTestId("health-export-end").fill("2026-11-26T11:00");
  const download = page.waitForEvent("download");
  await page.getByTestId("health-export-button").click();
  expect((await download).suggestedFilename()).toMatch(/^crosscut-logs-.*\.zip$/);
  const query = new URL(url).searchParams;
  expect(new Date(query.get("start") ?? "").getTime()).toBe(new Date("2026-11-26T10:00").getTime());
  expect(new Date(query.get("end") ?? "").getTime()).toBe(new Date("2026-11-26T11:00").getTime());
});

test("a refused export shows the server reason", async ({ page }) => {
  await openPage(page);
  await page.route(EXPORT_URL, (route) => json(route, 422, { detail: "the end of the range is before its start" }));
  await page.getByTestId("health-export-button").click();
  await expect(page.getByTestId("health-export-error")).toContainText("before its start");
});

for (const width of [1440, 390] as const) {
  test(`health view has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openPage(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    await expectNoSeriousAxe(page);
  });
}
