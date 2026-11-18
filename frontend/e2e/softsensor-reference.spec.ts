// Browser test of the soft sensor reference input (Polish): save the bundled example plus one reference
// input (window mean of a process tag, minimum coverage, bias weight) through the real API, upload the
// synthetic lab CSV, fit, run and read the reference table (coverage, valid windows, RMSE with and
// without the lab bias correction, verdict). Also axe (serious/critical none) at 1440 and 390 px.
// Needs the demo dataset and E2E_DATA_ROOT / E2E_PYTHON exactly like e2e/softsensor.spec.ts.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/softsensor`;
const SCRIPT = fileURLToPath(new URL("./support/make_lab_csv.py", import.meta.url));
const EXAMPLE = fileURLToPath(new URL("../../softsensor/examples/mill_circuit_pls.json", import.meta.url));
const REFERENCE = { tag: "sim.mc.mill_power", window_s: 1800, shift_s: 0, min_coverage: 0.8, bias_weight: 0.3 };

let labCsvPath = "";

/** The data root served by the API under test. */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.beforeAll(() => {
  labCsvPath = join(mkdtempSync(join(tmpdir(), "soft-ref-lab-")), "lab.csv");
  execFileSync(process.env.E2E_PYTHON ?? "python", [SCRIPT, dataRoot(), labCsvPath]);
});
test.describe.configure({ mode: "serial" });
test.beforeEach(() => rmSync(join(dataRoot(), "_softsensor"), { recursive: true, force: true }));
test.setTimeout(120_000);

/** Saves the example with the reference input through the API, then opens the page and fits and runs. */
async function fitAndRunWithReference(page: Page): Promise<void> {
  const example = JSON.parse(readFileSync(EXAMPLE, "utf-8")) as Record<string, unknown>;
  const saved = await page.request.put(`/api/softsensor/${String(example.id)}`, {
    data: { ...example, reference_inputs: [REFERENCE] },
  });
  expect(saved.ok()).toBeTruthy();
  await page.goto(PAGE_URL);
  await expect(page.getByLabel("Czujnik programowy")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("sim.mc.mill_power: 1800 s, przesunięcie 0 s, pokrycie co najmniej 80 %")).toBeVisible();
  // The origin of ISO times is filled when the dataset's start time has loaded.
  await expect(page.getByLabel(/^Czas początkowy dla czasów ISO/)).not.toHaveValue("");
  await page.getByLabel("Albo wybierz plik CSV").setInputFiles(labCsvPath);
  await expect(page.getByLabel("Wyniki laboratoryjne (tekst CSV)")).not.toBeEmpty();
  await page.getByRole("button", { name: "Wczytaj wyniki laboratoryjne" }).click();
  await expect(page.getByTestId("soft-lab-stored")).toContainText(/Zapisano: 72 wyników/, { timeout: 30_000 });
  await page.getByRole("button", { name: "Dopasuj model" }).click();
  await expect(page.getByRole("heading", { name: "Model", exact: true })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Uruchom", exact: true }).click();
  await expect(page.getByTestId("soft-result")).toBeVisible({ timeout: 60_000 });
}

test("the reference table shows coverage, validity and the bias check with and without correction", async ({ page }) => {
  await fitAndRunWithReference(page);
  const panel = page.getByTestId("soft-reference");
  await expect(panel.getByRole("heading", { name: "Wejścia referencyjne" })).toBeVisible();
  const row = page.getByTestId("soft-ref-sim.mc.mill_power");
  await expect(row.getByTestId("soft-ref-valid")).toContainText(/\d+[.,]\d %/);
  await expect(row).toContainText("1800 s / 0 s");
  await expect(row.getByTestId("soft-ref-verdict")).toHaveText(/pomaga|szkodzi|za mało wyników laboratoryjnych/);
  await expect(panel.getByRole("columnheader", { name: "RMSE bez korekty" })).toBeVisible();
  await expect(panel.getByRole("columnheader", { name: "RMSE z korektą" })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`reference panel has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await fitAndRunWithReference(page);
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
