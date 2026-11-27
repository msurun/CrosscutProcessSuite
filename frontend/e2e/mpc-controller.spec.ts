// Playwright end-to-end tests for the MPC part of the Controllers view (Phase 7.3, #184). The API
// answers are mocked with page.route (no runtime host): an MPC controller in advisory with CV/MV
// limits, a relaxed CV, predicted trajectories, an active constraint and a "why no move" reason.
// Checks the panel in en/pl/es, that the page sends nothing but the two reads, no horizontal
// scroll at 390 px and axe at 1440 and 390 px. The route is "#/controllers".
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";

const PAGE_URL = "/#/controllers";
const LIST_URL = /\/api\/controllers$/;
const ONE_URL = /\/api\/controllers\/M1$/;

const summary = {
  id: "M1",
  type: "mpc",
  description: "Grinding MIMO",
  cycle_s: 30,
  state: "advisory",
  reason: "advisory_only",
  last_cycle_utc: "2026-01-01T00:00:00+00:00",
  last_duration_s: 0.4,
  overruns: 0,
  consecutive_overruns: 0,
  liveness_utc: "2026-01-01T00:00:01+00:00",
  last_explanation: "feed: move | water: limit",
  disabled: [],
};

const ramp = (from: number, to: number) => Array.from({ length: 20 }, (_, i) => from + ((to - from) * i) / 19);

const diagnostics = {
  kind: "mpc",
  status: "solved",
  reason: "",
  why_no_move: null,
  shed_after: 3,
  cvs: [
    { id: "sump", value: 0.42, target: 0.5, lo: 0.1, hi: 0.9, relaxed: false, predicted: ramp(0.42, 0.5) },
    { id: "power", value: 4100, target: null, lo: 2000, hi: 4200, relaxed: true, predicted: ramp(4100, 4200) },
  ],
  mvs: [
    { id: "feed", sp: 100, proposed: 103, lo: 80, hi: 120, code: "move" },
    { id: "water", sp: 40, proposed: 40, lo: 30, hi: 40, code: "limit" },
  ],
  active_constraints: [
    { kind: "MV", variable: "water", side: "upper", sample: 1 },
    { kind: "CV", variable: "power", side: "upper", sample: 6 },
  ],
};

const detail = {
  ...summary,
  variables: [
    {
      id: "feed", role: "MV", binding: { loop: "WIC101" }, enabled: true,
      limits: { eng: { lo: 0, hi: 200 }, operator: { lo: 80, hi: 120 }, operator_catalogue: { lo: 80, hi: 120 } },
      status: "good", reasons: [], value: 100, sp_value: 100, source_utc: null,
    },
    {
      id: "sump", role: "CV", binding: { tag: "LIT201" }, enabled: true,
      limits: { operator_catalogue: null }, status: "good", reasons: [], value: 0.42, sp_value: null, source_utc: null,
    },
  ],
  diagnostics,
};

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, answer: unknown = detail) {
  await page.route(LIST_URL, (route) => json(route, 200, { controllers: [summary] }));
  await page.route(ONE_URL, (route) => json(route, 200, answer));
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
  await page.getByTestId("controller-open-M1").click();
  await expect(page.getByTestId("mpc-panel")).toBeVisible();
}

for (const language of ["en", "pl", "es"]) {
  const messages = JSON.parse(readFileSync(new URL(`../src/locales/${language}.json`, import.meta.url), "utf8"));
  test(`MPC panel shows limits, predictions and constraints in ${language}`, async ({ page }) => {
    await mockApi(page);
    await page.addInitScript((locale) => Object.defineProperty(navigator, "languages", { get: () => [locale] }), language);
    await openDetail(page);
    await expect(page.getByRole("heading", { name: messages["controllers.mpc.title"] })).toBeVisible();
    await expect(page.getByTestId("mpc-why")).toContainText(messages["controllers.mpc.moving"]);
    await expect(page.getByTestId("mpc-mv-water")).toContainText("30 .. 40");
    await expect(page.getByTestId("mpc-mv-water")).toContainText(messages["controllers.mpc.code.limit"]);
    await expect(page.getByTestId("mpc-cv-sump")).toContainText("0.1 .. 0.9");
    await expect(page.getByTestId("mpc-cv-power")).toContainText(messages["controllers.mpc.relaxed"]);
    await expect(page.getByTestId("mpc-chart-sump")).toHaveAttribute("role", "img");
    await expect(page.getByTestId("mpc-constraints").locator("li")).toHaveCount(2);
    await expectNoSeriousAxe(page);
  });
}

test("a cycle without a move names the reason", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "languages", { get: () => ["en"] }));
  await mockApi(page, { ...detail, diagnostics: { ...diagnostics, status: "hold", why_no_move: "hold", reason: "primal infeasible" } });
  await openDetail(page);
  await expect(page.getByTestId("mpc-why")).toContainText("held: no feasible plan this cycle");
  await expect(page.getByTestId("mpc-why")).toContainText("primal infeasible");
});

test("the page only reads: no write call leaves the browser", async ({ page }) => {
  await mockApi(page);
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET") writes.push(`${request.method()} ${request.url()}`);
  });
  await openDetail(page);
  expect(writes.filter((w) => !w.includes("/auth/"))).toEqual([]);
});

for (const width of [1440, 390] as const) {
  test(`MPC panel has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    await openDetail(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    await expectNoSeriousAxe(page);
  });
}
