// Browser test of the whole-PI-file import (Polish): upload a synthetic plant file plus its tag
// dictionary (made by e2e/support/make_plant_csv.py), read the preview in the Santiago time zone,
// see the detected loops and the Scavenger test window, import the dataset e2e_plant_<n>, and open
// the LIC-20103 loop. Also axe (serious/critical none) at 1440 and 390 px and no horizontal scroll
// at 390. The API only writes the new dataset folder under E2E_DATA_ROOT; the spec deletes that
// folder after each test and nothing else. E2E_PYTHON runs the CSV script (needs numpy).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const START_URL = "/#/d/level_integrating_demo/import";
const SCRIPT = fileURLToPath(new URL("./support/make_plant_csv.py", import.meta.url));

let fixtureDir = "";
let plantCsvPath = "";
let dictionaryCsvPath = "";
let created = "";

/** The data root served by the API under test. */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.beforeAll(() => {
  fixtureDir = mkdtempSync(join(tmpdir(), "import-plant-"));
  execFileSync(process.env.E2E_PYTHON ?? "python", [SCRIPT, fixtureDir]);
  plantCsvPath = join(fixtureDir, "plant.csv");
  dictionaryCsvPath = join(fixtureDir, "tag_dictionary.csv");
});

// Removes the dataset folder this test created (a direct child of the data root), nothing else.
test.afterEach(() => {
  const target = resolve(dataRoot(), created);
  if (created !== "" && dirname(target) === resolve(dataRoot())) {
    try {
      rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
    } catch {
      // Windows keeps the parquet file open while the API serves the dataset; the temp root is removed by the runner.
    }
  }
  created = "";
});
test.setTimeout(120_000);

/** Opens the Import view, switches to the whole-PI tab and loads both files. */
async function chooseFiles(page: Page): Promise<void> {
  await page.goto(START_URL);
  await page.getByRole("button", { name: "Cały plik PI" }).click();
  await expect(page.getByRole("button", { name: "Cały plik PI" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Plik z danymi (CSV, układ szeroki)").setInputFiles(plantCsvPath);
  await page.getByLabel("Słownik tagów (opcjonalnie)").setInputFiles(dictionaryCsvPath);
  await page.getByLabel("Strefa czasowa danych").selectOption({ label: "Santiago (Ameryka/Santiago)" });
}

/** Runs the preview and waits for the loops table to be filled. */
async function runPreview(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Wczytaj i sprawdź podgląd" }).click();
  await expect(page.getByRole("table", { name: "Wykryte pętle regulacji" })).toContainText("LIC-20101", { timeout: 60_000 });
}

test("preview, loops, test window, import and open the LIC-20103 loop", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("response", (r) => {
    if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);
  });
  await chooseFiles(page);
  await runPreview(page);
  const loopsTable = page.getByRole("table").filter({ hasText: "LIC-20101" });
  await expect(loopsTable).toContainText("LIC-20101");
  await expect(loopsTable).toContainText("LIC-20103");
  await expect(loopsTable).toContainText("FIC-20120");
  await expect(loopsTable).toContainText("Kompletna");
  await expect(page.getByRole("table").filter({ hasText: "Scavenger" })).toBeVisible();
  await expect(page.getByText(/America\/Santiago/).first()).toBeVisible();

  created = `e2e_plant_${Date.now()}_${info.workerIndex}`;
  await page.getByLabel("Identyfikator nowego zbioru danych").fill(created);
  await page.getByRole("button", { name: "Importuj zbiór danych" }).click();
  await expect(page.getByText("Import zakończony sukcesem")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Otwórz pętlę LIC-20103" }).click();
  await expect(page).toHaveURL(new RegExp(`/d/${created}/loops/LIC-20103/tuning`), { timeout: 30_000 });
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) {
  test(`plant import preview has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await chooseFiles(page);
    await runPreview(page);
    await page.waitForLoadState("networkidle");
    if (width === 390) {
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    }
    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}
