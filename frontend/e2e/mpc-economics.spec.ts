// Playwright end-to-end test for the MPC economic objective in the Controllers view (#187, P8 8.1).
// API answers are mocked with page.route: where-and-why from diagnostics.economics, editing the
// objective (the save sends PUT with empty fields omitted) and the benefit summary. Axe at 1440 px.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const summary = {
  id: "M1", type: "mpc", description: "Grinding MIMO", cycle_s: 30, state: "advisory", reason: "advisory_only",
  last_cycle_utc: "2026-01-01T00:00:00+00:00", last_duration_s: 0.4, overruns: 0, consecutive_overruns: 0,
  liveness_utc: "2026-01-01T00:00:01+00:00", last_explanation: "feed: move", disabled: [],
};
const ramp = Array.from({ length: 5 }, (_, i) => 0.4 + i * 0.02);
const diagnostics = {
  kind: "mpc", status: "solved", reason: "", why_no_move: null, shed_after: 3,
  cvs: [{ id: "sump", value: 0.42, target: 0.5, lo: 0.1, hi: 0.9, relaxed: false, predicted: ramp }],
  mvs: [{ id: "feed", sp: 100, proposed: 103, lo: 80, hi: 120, code: "move" }],
  active_constraints: [],
  economics: {
    status: "optimal", value_rate: 120, tracking_rate: 100, benefit_rate: 20, soft_limits_applied: true,
    binding: [{ kind: "MV", variable: "feed", side: "upper", limit: "soft", shadow_price: 3.5 }],
  },
};
const variable = (id: string, role: string) => ({
  id, role, binding: {}, enabled: true, limits: { operator_catalogue: null }, status: "good", reasons: [],
  value: 1, sp_value: null, source_utc: null,
});
const economics = { currency: "EUR", cv_value: { sump: 2 }, mv_cost: { feed: 0.5 }, soft_limits: { feed: { hi: 115 } }, source: "catalogue" };
const detail = { ...summary, variables: [variable("feed", "MV"), variable("sump", "CV")], diagnostics, economics };
const branch = {
  cvs: [], mvs: [], rate: [], settled_rate: 1, violations: { sump: [0, 0] },
  binding: [{ kind: "MV", index: 0, side: "upper", limit: "soft", share: 0.75, mean_shadow_price: 3 }], binding_over_time: [],
};
const benefit = {
  time_s: [0, 1], targets: [0.5], unit: "currency/h", benefit_rate: 18.5, value_gained: 37, cv_names: ["sump"], mv_names: ["feed"],
  tracking: branch, economic: branch,
};

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, puts: unknown[]) {
  await page.addInitScript(() => Object.defineProperty(navigator, "languages", { get: () => ["en"] }));
  await page.route(/\/api\/controllers$/, (route) => json(route, { controllers: [summary] }));
  await page.route(/\/api\/controllers\/M1$/, (route) => json(route, detail));
  await page.route(/\/api\/controllers\/M1\/economics$/, (route) => {
    puts.push(route.request().postDataJSON());
    return json(route, { ...detail, economics: { ...economics, ...puts[puts.length - 1] as object, source: "operator" } });
  });
  await page.route(/\/api\/mpc\/simulate\/benefit$/, (route) => json(route, benefit));
}

test("economic objective: where and why, edit and save, benefit summary", async ({ page }) => {
  const puts: unknown[] = [];
  await mockApi(page, puts);
  await page.goto("/#/controllers");
  await expect(page.getByTestId("controllers-list")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("controller-open-M1").click();

  await expect(page.getByTestId("economics-why")).toContainText("20 EUR/h");
  await expect(page.getByTestId("economics-binding")).toContainText("MV feed");
  await expect(page.getByTestId("economics-binding")).toContainText("3.5");

  await page.getByLabel(/^sump: Value per CV unit/).fill("");
  await page.getByLabel(/^feed: Cost per MV unit/).fill("0.8");
  await page.getByTestId("economics-save").click();
  await expect.poll(() => puts.length).toBe(1);
  expect(puts[0]).toEqual({ currency: "EUR", cv_value: {}, mv_cost: { feed: 0.8 }, soft_limits: { feed: { hi: 115 } } });

  await page.getByLabel("Identified model artifact id").fill("art1");
  for (const label of ["Maximum MV move per sample", "Maximum MV rate per second", "Maximum CV target rate per second",
    "CV funnel start widths", "CV funnel end widths"]) {
    await page.getByLabel(label).fill("1");
  }
  await page.getByTestId("economics-benefit-run").click();
  await expect(page.getByTestId("economics-benefit-result")).toContainText("18.5 EUR/h");
  await expect(page.getByTestId("economics-violations")).toContainText("Good: none");
  await expect(page.getByTestId("economics-benefit-binding")).toContainText("75 %");

  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
});
