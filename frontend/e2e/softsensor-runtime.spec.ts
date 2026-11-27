// Browser test of the soft sensor Runtime panel (Polish UI) with the soft sensor routes mocked by
// page.route: state with output, gate and events, a successful mode change, the exact 409 refusal
// text in an alert, and axe (serious/critical none) at 1440 and 390 px with no horizontal scroll.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/softsensor`;
const EXAMPLE = fileURLToPath(new URL("../../softsensor/examples/mill_circuit_pls.json", import.meta.url));
const CONFIG = JSON.parse(readFileSync(EXAMPLE, "utf-8")) as { id: string };
const SID = CONFIG.id;
const REFUSAL = "Deployment refused: no validated advantage over the available lab baseline.";

const STATE = {
  sensor_id: SID, mode: "shadow", changed_by: "operator", changed_utc: "2026-11-27T08:00:00Z",
  output: {
    t_utc: "2026-11-27T09:00:00Z", value: 12.5, status: "uncertain", reason: "extrapolation", source: "instrument",
    used_downstream: false, estimate: 12.4, bias: 0.1, drift: false, effective_mode: "shadow",
  },
  last_lab: { sample_utc: "2026-11-27T07:00:00Z", lab: 12, estimate: 12.4, residual: -0.4 },
  events: [{ t_utc: "2026-11-27T08:30:00Z", from: "instrument", to: "softsensor", reason: "frozen" }],
  gate: { available: true, deploy: false, skill: 0.02, reasons: ["skill below the lab baseline"], message: "Gate closed" },
};

/** Mocks the sensor list, config and runtime routes; returns the mode bodies the page PUT. */
async function mockBackend(page: Page, refuse: boolean): Promise<unknown[]> {
  const puts: unknown[] = [];
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route("**/api/softsensor", (route) => json(route, [SID]));
  await page.route(`**/api/softsensor/${SID}`, (route) => (route.request().method() === "GET" ? json(route, CONFIG) : route.fallback()));
  await page.route(`**/api/softsensor/${SID}/lab`, (route) => json(route, { detail: `no lab results uploaded: ${SID}` }, 404));
  await page.route(`**/api/softsensor/${SID}/model`, (route) => json(route, { detail: `model not fitted: ${SID}` }, 404));
  await page.route(`**/api/softsensor/${SID}/runtime`, (route) => json(route, STATE));
  await page.route(`**/api/softsensor/${SID}/mode`, (route) => {
    puts.push(route.request().postDataJSON());
    return refuse ? json(route, { detail: REFUSAL }, 409) : json(route, { ...STATE, mode: "backup" });
  });
  return puts;
}

async function openRuntime(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("soft-runtime").getByRole("heading", { name: "Praca online" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("soft-rt-status")).toBeVisible();
}

test("runtime panel shows the output, the events and the gate", async ({ page }) => {
  await mockBackend(page, false);
  await openRuntime(page);
  await expect(page.getByTestId("soft-rt-status")).toContainText("[?] Niepewna");
  await expect(page.getByTestId("soft-rt-reason")).toContainText("extrapolation");
  await expect(page.getByTestId("soft-rt-downstream")).toContainText("nie");
  await expect(page.getByTestId("soft-rt-events")).toContainText("frozen");
  await expect(page.getByTestId("soft-rt-gate")).toContainText("Wdrożenie dozwolone: nie");
});

test("a mode change is sent and the new mode is shown", async ({ page }) => {
  const puts = await mockBackend(page, false);
  await openRuntime(page);
  await page.getByLabel("Tryb pracy").selectOption("backup");
  await page.getByRole("button", { name: "Zastosuj" }).click();
  await expect(page.getByTestId("soft-rt-current")).toContainText("Zastępczy");
  expect(puts).toEqual([{ mode: "backup" }]);
});

test("a refusal shows the exact server text in an alert", async ({ page }) => {
  await mockBackend(page, true);
  await openRuntime(page);
  await page.getByLabel("Tryb pracy").selectOption("primary");
  await page.getByRole("button", { name: "Zastosuj" }).click();
  await expect(page.getByTestId("soft-rt-error")).toHaveText(REFUSAL);
  await expect(page.getByTestId("soft-rt-current")).toContainText("Cieniowy");
});

for (const width of [1440, 390]) {
  test(`runtime panel has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockBackend(page, true);
    await openRuntime(page);
    await page.getByLabel("Tryb pracy").selectOption("primary");
    await page.getByRole("button", { name: "Zastosuj" }).click();
    await expect(page.getByTestId("soft-rt-error")).toHaveText(REFUSAL);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}
