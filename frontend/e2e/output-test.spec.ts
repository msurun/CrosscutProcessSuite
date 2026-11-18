// Exercise the live-write confirmation slice in each supported locale.
// Mailbox replies are mocked here; L5 separately verifies physical OUT restoration.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

/** Read the shipped translations without relying on Node's JSON import dialect. */
function messagesFor(language: string): Record<string, string> {
  return JSON.parse(readFileSync(new URL(`../src/locales/${language}.json`, import.meta.url), "utf8"));
}

/** Serve synthetic catalogue data so the browser slice does not need a plant or ASGI server. */
async function mockCatalogue(page: Page): Promise<void> {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith("/auth/config")) json = { auth_enabled: false, initialised: true };
    if (path.endsWith("/loops")) json = { loops: [] };
    if (path.endsWith("/datasets")) json = [{
      id: "mill_circuit_step_test_seed42", source: {}, n_tags: 0, n_samples: 0,
      time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" },
    }];
    return route.fulfill({ json });
  });
}

for (const language of ["en", "pl", "es"]) {
  const messages = messagesFor(language);
  test(`OUT confirmation, cancel and axe in ${language}`, async ({ page }) => {
    await mockCatalogue(page);
    await page.addInitScript((locale) => { Object.defineProperty(navigator, "languages", { get: () => [locale] }); }, language);
    await page.route(/\/api\/gateway\/output-tests(?:\/.*)?$/, (route) => route.fulfill({
      json: { accepted: true, reason_code: route.request().url().endsWith("/cancel") ? "restored" : "out_step_started" },
    }));
    await page.goto("/#/d/mill_circuit_step_test_seed42/steps");
    const section = page.getByRole("region", { name: messages["outTest.title"] });
    await section.getByLabel(messages["outTest.target"]).fill("FIC203.OUT");
    await section.getByLabel(messages["outTest.amplitude"]).fill("1");
    await section.getByLabel(messages["outTest.duration"]).fill("5");
    await section.getByRole("button", { name: messages["outTest.confirm"] }).click();
    await expect(section.getByRole("status")).toContainText("out_step_started");
    await section.getByRole("button", { name: messages["outTest.cancel"] }).click();
    await expect(section.getByRole("status")).toContainText("restored");
    const results = await new AxeBuilder({ page }).include("section[aria-label]").analyze();
    expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
  });
}
