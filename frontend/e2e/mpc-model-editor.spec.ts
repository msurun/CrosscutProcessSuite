// Exercise immutable MPC model editing against synthetic page.route replies.
// The browser checks the matrix, audited override request, plots and accessibility.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PARENT_SHA256 = "a".repeat(64);
const QUALITY = { passed: true, reasons: [], free_run_r2: 0.98, excitation_events: 3 };
const PAIRS = [
  { input_name: "reflux", cv_name: "purity", gain: 2, time_constant_s: 60,
    dead_time_s: 10, enabled: true, quality: QUALITY },
  { input_name: "feed", cv_name: "purity", gain: -1, time_constant_s: 30,
    dead_time_s: 5, enabled: true, quality: { ...QUALITY, passed: false, reasons: ["weak excitation"] } },
];
const MODEL = { model_id: "wood-berry", sha256: PARENT_SHA256,
  input_names: ["reflux", "feed"], cv_names: ["purity"], cycle_s: 5, pairs: PAIRS,
  parent_model_id: null, parent_sha256: null, author: null, reason: null };
const DATASETS = [{ id: "synthetic", source: {}, n_tags: 0, n_samples: 0,
  time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" } }];

/** Build a separate version exactly from the submitted override fields. */
function editedVersion(body: Record<string, unknown>) {
  return { ...MODEL, model_id: "wood-berry-edited", sha256: "b".repeat(64),
    pairs: (body.pairs as typeof PAIRS).map((pair, index) => ({ ...pair, quality: PAIRS[index].quality })),
    parent_model_id: MODEL.model_id, parent_sha256: PARENT_SHA256,
    author: body.author, reason: body.reason };
}

/** Serve the Steps dependencies and model endpoints without a running API. */
async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith("/auth/config")) json = { auth_enabled: false, initialised: true };
    if (path.endsWith("/loops")) json = { loops: [] };
    if (path.endsWith("/datasets")) json = DATASETS;
    if (path === "/api/mpc/models/wood-berry") json = MODEL;
    if (route.request().method() === "POST") {
      expect(path).toBe("/api/mpc/models/wood-berry/versions");
      json = editedVersion(route.request().postDataJSON());
    }
    return route.fulfill({ json });
  });
}

/** Open the English console and load a synthetic two-input model. */
async function openEditor(page: Page) {
  await mockApi(page);
  await page.addInitScript(() => Object.defineProperty(navigator, "languages", { get: () => ["en"] }));
  await page.goto("/#/d/synthetic/steps");
  const panel = page.getByRole("region", { name: "MPC model matrix", exact: true });
  await panel.getByLabel("Model artifact id", { exact: true }).fill(MODEL.model_id);
  await panel.getByRole("button", { name: "Load model", exact: true }).click();
  await expect(panel.getByRole("table", { name: "MV/DV × CV model matrix" })).toBeVisible();
  return panel;
}

test("loads gains, time parameters, quality and one unit-step plot per pair", async ({ page }) => {
  const panel = await openEditor(page);
  await expect(panel.getByLabel("Gain reflux → purity", { exact: true })).toHaveValue("2");
  await expect(panel.getByLabel("Time constant (s) reflux → purity", { exact: true })).toHaveValue("60");
  await expect(panel.getByLabel("Dead time (s) reflux → purity", { exact: true })).toHaveValue("10");
  await expect(panel.getByLabel("Enabled feed → purity", { exact: true })).toBeChecked();
  await expect(panel.getByRole("table")).toContainText("weak excitation");
  await expect(panel.getByRole("img")).toHaveCount(2);
  const results = await new AxeBuilder({ page }).include("section[aria-label]").analyze();
  expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
});

test("saves a reasoned override and disabled pair as a new version linked to its parent", async ({ page }) => {
  const panel = await openEditor(page);
  await panel.getByLabel("Gain reflux → purity", { exact: true }).fill("3");
  await panel.getByLabel("Time constant (s) reflux → purity", { exact: true }).fill("75");
  await panel.getByLabel("Dead time (s) reflux → purity", { exact: true }).fill("12");
  await panel.getByLabel("Enabled feed → purity", { exact: true }).uncheck();
  await panel.getByLabel("Author", { exact: true }).fill("Engineer");
  await panel.getByLabel("Reason for the new version", { exact: true }).fill("Verified against repeat step test");
  const request = page.waitForRequest((request) => request.method() === "POST");
  await panel.getByRole("button", { name: "Save as new version", exact: true }).click();
  expect((await request).postDataJSON()).toMatchObject({ parent_sha256: PARENT_SHA256,
    author: "Engineer", reason: "Verified against repeat step test", pairs: [
      { input_name: "reflux", cv_name: "purity", gain: 3, time_constant_s: 75, dead_time_s: 12, enabled: true },
      { input_name: "feed", cv_name: "purity", enabled: false },
    ] });
  await expect(panel.getByRole("status")).toContainText("wood-berry-edited");
  expect(MODEL.pairs[0].gain).toBe(2);
});

test("requires an override reason before saving a changed gain", async ({ page }) => {
  const panel = await openEditor(page);
  await panel.getByLabel("Gain reflux → purity", { exact: true }).fill("3");
  await panel.getByLabel("Author", { exact: true }).fill("Engineer");
  await expect(panel.getByLabel("Reason for the new version", { exact: true })).toHaveAttribute("required", "");
  await expect(panel.getByRole("button", { name: "Save as new version", exact: true })).toBeDisabled();
  await panel.getByLabel("Reason for the new version", { exact: true }).fill("   ");
  await expect(panel.getByRole("button", { name: "Save as new version", exact: true })).toBeDisabled();
  await panel.getByLabel("Reason for the new version", { exact: true }).fill("Repeat test confirmed the gain");
  await expect(panel.getByRole("button", { name: "Save as new version", exact: true })).toBeEnabled();
});
