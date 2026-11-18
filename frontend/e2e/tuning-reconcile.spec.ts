// Playwright end-to-end tests for the open-write-intent reconcile card in the Tuning view.
// The API is mocked with page.route (as in tuning.spec.ts): GET /tuning/intents, the resolve call
// that first answers 428 step_up_required, and /auth/stepup. Checks intended vs current values,
// the step-up prompt, the card disappearing, the damaged-store notice and axe at 1440 and 390 px.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/tuning`;

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const INTENT = {
  key: "k-intent-1",
  loop_id: "FIC1",
  created_at: "2026-11-05T10:00:00Z",
  proposer: "alice",
  targets: [
    { target: "FIC1.GAIN", to_value: 1.5, current_value: 1.25 },
    { target: "FIC1.TI", to_value: 45, current_value: null },
  ],
};

// A signed-in operator: the step-up call needs a CSRF token, which only a session carries.
const SESSION = {
  user: { username: "bob", display_name: "Bob" },
  roles: ["operator"],
  permissions: ["gw.approve.tuning"],
  csrf: "csrf-token",
  must_change_password: false,
  stepup_valid: false,
};

async function mockApi(page: Page, payload: () => unknown) {
  await page.route(/\/api\/tuning\/proposals(\?.*)?$/, (route) => json(route, 200, []));
  await page.route(/\/api\/tuning\/intents(\?.*)?$/, (route) => json(route, 200, payload()));
}

async function expectNoSeriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`),
  ).toEqual([]);
}

test("the card shows intended and current values of an open intent", async ({ page }) => {
  await mockApi(page, () => ({ store_state: "ok", intents: [INTENT] }));
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("tuning-reconcile-card")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("tuning-reconcile-card")).toContainText("FIC1");
  await expect(page.getByTestId("reconcile-intended-FIC1.GAIN")).toHaveText("1.5");
  await expect(page.getByTestId("reconcile-current-FIC1.GAIN")).toHaveText("1.25");
  await expect(page.getByTestId("reconcile-intended-FIC1.TI")).toHaveText("45");
  await expect(page.getByTestId("reconcile-current-FIC1.TI")).toContainText("nieznana");
});

test("resolving goes through the step-up prompt and removes the card", async ({ page }) => {
  let resolved = false;
  let resolveCalls = 0;
  await mockApi(page, () => ({ store_state: "ok", intents: resolved ? [] : [INTENT] }));
  await page.route(/\/api\/auth\/config$/, (route) => json(route, 200, { auth_enabled: true, initialised: true }));
  await page.route(/\/api\/auth\/me$/, (route) => json(route, 200, SESSION));
  await page.route(/\/api\/auth\/stepup$/, (route) => json(route, 200, { ok: true, valid_for_s: 300 }));
  await page.route(/\/api\/tuning\/intents\/[^/]+\/resolve$/, (route) => {
    resolveCalls += 1;
    if (resolveCalls === 1) return json(route, 428, { detail: "step_up_required" });
    resolved = true;
    return json(route, 200, { ok: true });
  });
  await page.goto(PAGE_URL);
  await page.getByTestId("reconcile-resolve").click();
  await expect(page.getByTestId("stepup-dialog")).toBeVisible({ timeout: 30_000 });
  await page.locator("#stepup-password").fill("any-password-123");
  await page.getByTestId("stepup-submit").click();
  await expect(page.getByTestId("stepup-dialog")).toBeHidden({ timeout: 30_000 });
  await expect(page.getByTestId("tuning-reconcile-card")).toHaveCount(0, { timeout: 30_000 });
  expect(resolveCalls).toBe(2);
});

test("a damaged intent store shows the blocking message", async ({ page }) => {
  await mockApi(page, () => ({ store_state: "damaged", intents: [] }));
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("tuning-store-damaged")).toContainText("uszkodzony", { timeout: 30_000 });
  await expect(page.getByTestId("tuning-reconcile-card")).toHaveCount(0);
});

for (const width of [1440, 390] as const) {
  test(`reconcile card and damaged notice have no axe violations @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page, () => ({ store_state: "damaged", intents: [INTENT] }));
    await page.goto(PAGE_URL);
    await expect(page.getByTestId("tuning-reconcile-card")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("tuning-store-damaged")).toBeVisible();
    await expectNoSeriousAxe(page);
  });
}
