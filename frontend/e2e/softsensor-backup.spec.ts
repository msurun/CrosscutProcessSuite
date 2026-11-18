// Browser test of the soft sensor backup mode (Polish UI): save the bundled example plus a backup
// block through the real API (the lowest ~30 % of a process tag count as out of range, so the output
// is substituted and the measurement returns after the hold time), upload the synthetic lab CSV, fit,
// run and read the status chip, quality line and switch history. Also axe (serious/critical none) at
// 1440 and 390 px. Needs the demo dataset and E2E_DATA_ROOT / E2E_PYTHON like e2e/softsensor.spec.ts.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/softsensor`;
const LAB_SCRIPT = fileURLToPath(new URL("./support/make_lab_csv.py", import.meta.url));
const RANGE_SCRIPT = fileURLToPath(new URL("./support/backup_range.py", import.meta.url));
const EXAMPLE = fileURLToPath(new URL("../../softsensor/examples/mill_circuit_pls.json", import.meta.url));
const MEASURED_TAG = "sim.mc.mill_feed";
const LOW_PERCENTILE = "30";

let labCsvPath = "";
let rangeLo = 0;

/** The data root served by the API under test. */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.beforeAll(() => {
  const python = process.env.E2E_PYTHON ?? "python";
  labCsvPath = join(mkdtempSync(join(tmpdir(), "soft-backup-lab-")), "lab.csv");
  execFileSync(python, [LAB_SCRIPT, dataRoot(), labCsvPath]);
  rangeLo = Number(execFileSync(python, [RANGE_SCRIPT, dataRoot(), MEASURED_TAG, LOW_PERCENTILE]).toString().trim());
});
test.describe.configure({ mode: "serial" });
test.beforeEach(() => rmSync(join(dataRoot(), "_softsensor"), { recursive: true, force: true }));
test.setTimeout(120_000);

/** Saves the example with a backup block through the API, then opens the page, fits and runs. */
async function fitAndRunWithBackup(page: Page): Promise<void> {
  const example = JSON.parse(readFileSync(EXAMPLE, "utf-8")) as Record<string, unknown>;
  const backup = { enabled: true, measured_tag: MEASURED_TAG, frozen_s: 100000, range_lo: rangeLo, range_hi: 1e9, return_hold_s: 120 };
  const saved = await page.request.put(`/api/softsensor/${String(example.id)}`, { data: { ...example, backup } });
  expect(saved.ok()).toBeTruthy();
  await page.goto(PAGE_URL);
  await expect(page.getByLabel("Czujnik programowy")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/sim\.mc\.mill_feed: zastępowanie, gdy wartość stoi przez 100000 s/)).toBeVisible();
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

test("backup panel shows the substitution status, quality code and the switch history", async ({ page }) => {
  await fitAndRunWithBackup(page);
  const panel = page.getByTestId("soft-backup");
  await expect(panel.getByRole("heading", { name: "Tryb zastępczy" })).toBeVisible();
  await expect(panel.getByTestId("soft-backup-status")).toHaveText(/Zastąpiona przez czujnik wirtualny|Używana wartość zmierzona/);
  await expect(panel.getByTestId("soft-backup-quality")).toContainText(/Kod jakości [012]/);
  await expect(panel.getByTestId("soft-backup-count")).not.toHaveText("Zastąpione wiersze: 0");
  const rows = panel.getByTestId("soft-backup-switches").getByRole("row");
  await expect(rows.nth(1)).toContainText("poza zakresem");
  await expect(panel.getByRole("columnheader", { name: "Powód" })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`backup panel has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await fitAndRunWithBackup(page);
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
