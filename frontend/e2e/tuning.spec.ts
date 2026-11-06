// Playwright end-to-end tests for the Tuning proposals view (ADR 014, step 8). The API answers are
// mocked with page.route (no gateway process here): the list, one proposal with a KPI review, the
// approve call and its refusals. Checks the tab, the detail, the approve dialog with its tick,
// the mapped refusal message, no horizontal page scroll at 390 px and axe at 1440 and 390 px.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/tuning`;
const LIST_URL = /\/api\/tuning\/proposals(\?.*)?$/;
const ONE_URL = /\/api\/tuning\/proposals\/[^/]+(\/(approve|reject|rollback))?$/;

function proposal(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    loop_id: `FIC${id.replace(/\D/g, "") || "1"}`,
    created_by: "alice",
    created_at: "2026-11-05T10:00:00Z",
    expires_at: "2099-01-01T00:00:00Z",
    vendor_form: { key: "siemens_pid_compact", evidence: "verified" },
    source: {
      method: "simc",
      robustness: 0.5,
      window: { dataset_id: DATASET, start: "2026-11-05T08:00:00Z", end: "2026-11-05T09:00:00Z" },
      step_test_id: "st-1",
    },
    confidence: { level: "medium", reasons: ["no step test referenced"] },
    caveats: ["Ti is in seconds <b>not bold</b>"],
    items: [
      { param: "gain", target: "FIC1.GAIN", unit: "-", from: 1, to: 1.5 },
      { param: "ti", target: "FIC1.TI", unit: "s", from: 30, to: 45 },
    ],
    preview: {
      label: "model prediction",
      iae_ratio: 0.8,
      overshoot_pct: { current: 12, proposed: 5 },
      settling_time_s: { current: 100, proposed: 70 },
      ms: { current: 1.8, proposed: 1.5 },
    },
    rollback_of: null,
    status: "queued",
    gateway_key: "k1",
    applied: null,
    review: null,
    rollback_recommended: false,
    ...over,
  };
}

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, list: unknown[]) {
  await page.route(LIST_URL, (route) => json(route, 200, list));
  await page.route(ONE_URL, (route) => json(route, 200, list[0]));
}

async function expectNoSeriousAxe(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`),
  ).toEqual([]);
}

async function openFirst(page: Page) {
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("tuning-list")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("tuning-list").getByRole("button").first().click();
  await expect(page.getByTestId("tuning-detail")).toBeVisible();
}

test("the Tuning tab opens the proposals view with the detail of a proposal", async ({ page }) => {
  await mockApi(page, [proposal("p1")]);
  await page.goto(`/#/d/${DATASET}/trends`);
  await page.locator("nav.view-tabs button").filter({ hasText: /Nastawy/ }).click();
  await expect(page.getByTestId("tuning-proposals-page")).toBeVisible({ timeout: 30_000 });
  await openFirst(page);
  await expect(page.getByTestId("tuning-items")).toContainText("FIC1.TI");
  await expect(page.getByTestId("tuning-preview")).toContainText("predykcja modelu");
  await expect(page.getByTestId("tuning-caveats")).toContainText("<b>not bold</b>");
  await expect(page.locator("[data-testid=tuning-caveats] b")).toHaveCount(0);
});

test("a worse review shows the note and the rollback badge", async ({ page }) => {
  const review = { verdict: "worse", reasons: ["error_std_up"], before: { n: 100 }, after: { n: 90 } };
  await mockApi(page, [proposal("p1", { status: "reviewed:worse", review, rollback_recommended: true })]);
  await openFirst(page);
  await expect(page.getByTestId("tuning-rollback-recommended")).toBeVisible();
  await expect(page.getByTestId("tuning-review-note")).toContainText("nie są wykluczone");
});

test("approve needs the tick and shows a refusal of the gateway", async ({ page }) => {
  await mockApi(page, [proposal("p1")]);
  await page.route(/\/approve$/, (route) => json(route, 409, { detail: "from_mismatch" }));
  await openFirst(page);
  await page.getByTestId("tuning-approve").click();
  await expect(page.getByTestId("tuning-approve-dialog")).toBeVisible();
  await expect(page.getByTestId("tuning-approve-confirm")).toHaveAttribute("aria-disabled", "true");
  await page.getByTestId("tuning-approve-check").check();
  await page.getByTestId("tuning-approve-confirm").click();
  await expect(page.getByTestId("tuning-action-error")).toContainText("Wartość w DCS różni się");
});

for (const width of [1440, 390] as const) {
  test(`proposals view has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const many = Array.from({ length: 100 }, (_, i) => proposal(`p${i + 1}`, { loop_id: `FIC${i + 1}` }));
    await mockApi(page, many);
    await openFirst(page);
    await expect(page.getByTestId("tuning-list").getByRole("row")).toHaveCount(101);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    await expectNoSeriousAxe(page);
  });

  test(`approve dialog has no axe violations @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page, [proposal("p1")]);
    await openFirst(page);
    await page.getByTestId("tuning-approve").click();
    await expect(page.getByTestId("tuning-approve-dialog")).toBeVisible();
    await expectNoSeriousAxe(page);
  });
}

test("the empty list shows the hint", async ({ page }) => {
  await mockApi(page, []);
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("tuning-empty")).toBeVisible({ timeout: 30_000 });
  await expectNoSeriousAxe(page);
});
