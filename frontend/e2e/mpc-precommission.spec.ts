// Browser comparison on a synthetic identified model, with no live controller writes.
// Each locale checks scenario payload, constraint charts, KPI results and accessibility.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const COUNTERS = { cv: [0], mv: [0], move: [0], rate: [0] };
const TRACE = { cvs: [[0], [0.5], [1]], mvs: [[0], [1], [0.5]],
  kpis: { iae: [1.5], overshoot: [0], settling_time_s: [2], mv_travel: [1.5], constraint_violations: COUNTERS } };
const RESULT = { time_s: [0, 1, 2], targets: [[0], [1], [1]], disturbances: [[], [], []],
  mpc: TRACE, pid: TRACE, cv_names: ["purity"], mv_names: ["reflux"],
  limits: { mv_lower: [-1], mv_upper: [1], cv_lower: [-2], cv_upper: [2] } };
const LIMITS = ["mv_lower", "mv_upper", "cv_lower", "cv_upper", "priorities", "move_max",
  "rate_max", "target_rate", "funnel_start", "funnel_end"];

/** Route every request locally and assert the comparison has no write endpoint. */
async function mockApi(page: Page) {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith("/auth/config")) json = { auth_enabled: false, initialised: true };
    if (path.endsWith("/loops")) json = { loops: [] };
    if (path.endsWith("/datasets")) json = [{ id: "synthetic", source: {}, n_tags: 0, n_samples: 0,
      time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" } }];
    if (route.request().method() === "POST") {
      expect(path).toBe("/api/mpc/simulate");
      expect(route.request().postDataJSON().scenario.kind).toBe("constraint_active");
      json = RESULT;
    }
    return route.fulfill({ json });
  });
}

for (const language of ["en", "pl", "es"]) {
  const messages = JSON.parse(readFileSync(new URL(`../src/locales/${language}.json`, import.meta.url), "utf8"));
  test(`MPC pre-commissioning comparison and axe in ${language}`, async ({ page }) => {
    await mockApi(page);
    await page.addInitScript((locale) => Object.defineProperty(navigator, "languages", { get: () => [locale] }), language);
    await page.goto("/#/d/synthetic/steps");
    const panel = page.getByRole("region", { name: messages["precommission.title"] });
    await panel.getByLabel(messages["precommission.artifact_id"]).fill("wood-berry");
    await panel.getByLabel(messages["precommission.controller_id"]).fill("C1");
    for (const key of LIMITS) await panel.getByLabel(messages[`precommission.${key}`]).fill(key.endsWith("lower") ? "-2" : "2");
    for (const [key, value] of Object.entries({ loop_id: "LA", kp: "0.2", ti_s: "60", td_s: "0" })) {
      await panel.getByLabel(messages[`precommission.${key}`]).fill(value);
    }
    await panel.getByLabel(messages["precommission.scenario"]).selectOption("constraint_active");
    await panel.getByRole("button", { name: messages["precommission.run"] }).click();
    await expect(panel.getByRole("table")).toBeVisible();
    await expect(panel.getByRole("img")).toHaveCount(2);
    const results = await new AxeBuilder({ page }).include("section[aria-label]").analyze();
    expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
  });
}
