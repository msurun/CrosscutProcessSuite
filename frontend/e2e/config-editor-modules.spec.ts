// Browser coverage of the shared editor in its three module views.
// Uses the same API/Vite scratch-data stack as the other module specs.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const CONFIG_ID = "e2e_config_editor";
const MODULE_FILES = {
  supervisor: "supervisor/examples/mill_feed_advisor.json",
  anomaly: "anomaly/examples/mill_circuit_pca.json",
  softsensor: "softsensor/examples/mill_circuit_pls.json",
};
type ModuleKind = keyof typeof MODULE_FILES;

/** Refuse to seed anywhere except the scratch data root supplied by the support stack. */
function configPath(kind: ModuleKind): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT using npm run e2e:all.");
  return join(root, `_${kind}`, `${CONFIG_ID}.json`);
}

/** Give each module an independent configuration without altering other specs' examples. */
function seedConfiguration(kind: ModuleKind): void {
  const document = JSON.parse(readFileSync(resolve("..", MODULE_FILES[kind]), "utf-8"));
  document.id = CONFIG_ID;
  const path = configPath(kind);
  mkdirSync(resolve(path, ".."), { recursive: true });
  writeFileSync(path, JSON.stringify(document), "utf-8");
}

test.beforeEach(() => {
  seedConfiguration("supervisor");
  seedConfiguration("anomaly");
  seedConfiguration("softsensor");
});
test.afterAll(() => {
  rmSync(configPath("supervisor"), { force: true });
  rmSync(configPath("anomaly"), { force: true });
  rmSync(configPath("softsensor"), { force: true });
});

/** The free-tag anomaly config lives under the Advanced tab of the equipment Anomalies view (#216). */
async function openAdvancedIfAnomalies(page: Page, view: string): Promise<void> {
  if (view === "anomalies") {
    await page.getByRole("button", { name: /^(Advanced|Zaawansowane|Avanzado)$/ }).click();
  }
}

/** Exercise persistence through the real module API, then check the rendered form with axe. */
async function editSaveReload(page: Page, view: string, route: string): Promise<void> {
  await page.goto(`/#/d/${DATASET}/${view}`);
  await openAdvancedIfAnomalies(page, view);
  await page.locator(`select:has(option[value="${CONFIG_ID}"])`).selectOption(CONFIG_ID);
  const editor = page.getByRole("region", { name: /Configuration|Konfiguracja/ });
  const description = editor.locator("#schema-field-description");
  await expect(description).toBeVisible();
  await description.fill(`Saved ${view} description`);
  const saved = page.waitForResponse((response) => response.url().endsWith(`/api/${route}/${CONFIG_ID}`)
    && response.request().method() === "PUT" && response.ok());
  await editor.getByRole("button", { name: /^(Save|Zapisz)$/ }).click();
  await saved;
  await expect(editor.getByRole("status")).toBeVisible();
  await description.fill("Unsaved change");
  await editor.getByRole("button", { name: /Reload|Wczytaj ponownie/ }).click();
  await expect(description).toHaveValue(`Saved ${view} description`);
  await checkAccessibility(page, view, `Saved ${view} description`);
}

/** Check the persisted document after a full page load, then inspect accessibility. */
async function checkAccessibility(page: Page, view: string, expectedDescription: string): Promise<void> {
  await page.reload();
  await openAdvancedIfAnomalies(page, view);
  await page.locator(`select:has(option[value="${CONFIG_ID}"])`).selectOption(CONFIG_ID);
  await expect(page.locator("#schema-field-description")).toHaveValue(expectedDescription);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""))).toEqual([]);
}

test("edits, saves and reloads supervisor configuration with accessible fields", async ({ page }) => {
  await editSaveReload(page, "advisory", "supervisors");
});
test("edits, saves and reloads anomaly configuration with accessible fields", async ({ page }) => {
  await editSaveReload(page, "anomalies", "anomaly");
});
test("edits, saves and reloads soft sensor configuration with accessible fields", async ({ page }) => {
  await editSaveReload(page, "softsensor", "softsensor");
});
