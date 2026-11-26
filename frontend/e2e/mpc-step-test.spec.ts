// Browser slice of the multi-MV step planner: preview, confirm, abort and axe, in every locale.
// API replies are mocked; Python tests cover the gateway path and the abort rules.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

/** Read the shipped translations without relying on Node's JSON import dialect. */
function messagesFor(language: string): Record<string, string> {
  return JSON.parse(readFileSync(new URL(`../src/locales/${language}.json`, import.meta.url), "utf8"));
}

const STEP = { index: 0, mv: "mva", tag: "a.sp", at_s: 0, value: 53 };
const RECORD = { id: "p1", status: "running", steps: [{ ...STEP, status: "queued" }], abort_reason: null, displaced: [] };

/** Serve synthetic catalogue data so the slice needs neither a plant nor an ASGI server. */
async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith("/auth/config")) json = { auth_enabled: false, initialised: true };
    if (path.endsWith("/loops")) json = { loops: [] };
    if (path.endsWith("/datasets")) json = [{
      id: "mill_circuit_step_test_seed42", source: {}, n_tags: 0, n_samples: 0,
      time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" },
    }];
    if (path.endsWith("/mpc/step-plans/preview")) json = {
      ok: true, digest: "d".repeat(64), steps: [STEP], refusals: [], gateway_mode: "confirm",
    };
    if (path.endsWith("/mpc/step-plans")) json = RECORD;
    if (path.endsWith("/abort")) json = { ...RECORD, status: "aborted", abort_reason: "operator_abort" };
    if (path.endsWith("/advance")) json = RECORD;
    return route.fulfill({ json });
  });
}

for (const language of ["en", "pl", "es"]) {
  const messages = messagesFor(language);
  test(`step planner preview, confirm, abort and axe in ${language}`, async ({ page }) => {
    await mockApi(page);
    await page.addInitScript((locale) => { Object.defineProperty(navigator, "languages", { get: () => [locale] }); }, language);
    await page.goto("/#/d/mill_circuit_step_test_seed42/steps");
    const section = page.getByRole("region", { name: messages["stepPlan.title"] });
    await section.getByLabel(messages["stepPlan.controller_id"]).fill("C1");
    await section.getByLabel(messages["stepPlan.variable_id"]).fill("mva");
    await section.getByLabel(messages["stepPlan.amplitude"]).fill("3");
    await section.getByLabel(messages["stepPlan.duration_s"]).fill("120");
    await section.getByRole("button", { name: messages["stepPlan.preview"] }).click();
    await expect(section.getByRole("table")).toBeVisible();
    await section.getByRole("button", { name: messages["stepPlan.confirm"] }).click();
    await expect(section.getByRole("status")).toContainText(messages["stepPlan.status.running"]);
    await section.getByRole("button", { name: messages["stepPlan.abort"] }).click();
    await expect(section.getByRole("status")).toContainText(messages["stepPlan.status.aborted"]);
    const results = await new AxeBuilder({ page }).include("section[aria-label]").analyze();
    expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
  });
}
