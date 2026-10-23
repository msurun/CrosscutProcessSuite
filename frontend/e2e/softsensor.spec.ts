// Browser test of the Soft sensor page (Polish): load the example config, upload a synthetic lab CSV
// (made by e2e/support/make_lab_csv.py from the demo dataset), fit, run, see the chart and the
// validity counts. Also axe (serious/critical none) at 1440 and 390 px and no horizontal scroll at 390.
// Needs the demo dataset `mill_circuit_observational_seed42`; the API writes to its data root
// (_softsensor), so use a scratch copy and pass its path in E2E_DATA_ROOT: before each test the spec
// deletes the _softsensor folder there. The lab CSV script needs numpy and pyarrow: E2E_PYTHON is the
// interpreter to run it with (default "python").
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/softsensor`;
const SCRIPT = fileURLToPath(new URL("./support/make_lab_csv.py", import.meta.url));

let labCsvPath = "";

/** The data root served by the API under test. */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.beforeAll(() => {
  labCsvPath = join(mkdtempSync(join(tmpdir(), "soft-lab-")), "lab.csv");
  execFileSync(process.env.E2E_PYTHON ?? "python", [SCRIPT, dataRoot(), labCsvPath]);
});
// The tests share one stored state (_softsensor), so they must not run in two workers at once.
test.describe.configure({ mode: "serial" });
test.beforeEach(() => rmSync(join(dataRoot(), "_softsensor"), { recursive: true, force: true }));
// Fit and run read the whole record; under load (two workers) that can take a while.
test.setTimeout(120_000);

/** Opens the page and loads the bundled example. */
async function openWithExample(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await page.getByRole("button", { name: "Wczytaj przykład" }).click();
  await expect(page.getByLabel("Czujnik programowy")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("note").first()).toContainText("Tylko doradztwo");
}

/** Chooses the lab CSV file and uploads it. */
async function uploadLab(page: Page): Promise<void> {
  await page.getByLabel("Albo wybierz plik CSV").setInputFiles(labCsvPath);
  await expect(page.getByLabel("Wyniki laboratoryjne (tekst CSV)")).not.toBeEmpty();
  await page.getByRole("button", { name: "Wczytaj wyniki laboratoryjne" }).click();
  await expect(page.getByTestId("soft-lab-stored")).toContainText(/Zapisano: 72 wyników/, { timeout: 30_000 });
}

/** Load example, upload, fit on the default train end and run over the whole record. */
async function loadFitAndRun(page: Page): Promise<void> {
  await openWithExample(page);
  await uploadLab(page);
  await page.getByRole("button", { name: "Dopasuj model" }).click();
  await expect(page.getByRole("heading", { name: "Model", exact: true })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Uruchom", exact: true }).click();
  await expect(page.getByTestId("soft-result")).toBeVisible({ timeout: 60_000 });
}

test("load example, upload lab results, fit, run and read the result", async ({ page }) => {
  await loadFitAndRun(page);
  await expect(page.getByRole("note").nth(1)).toContainText("nie zostało sprawdzone na rzeczywistej instalacji");
  await expect(page.getByTestId("soft-estimate-chart").locator("canvas").first()).toBeVisible();
  await expect(page.getByTestId("soft-bias-chart").locator("canvas").first()).toBeVisible();
  await expect(page.getByText(/Nie używaj oszacowania tam, gdzie widoczna jest flaga/)).toBeVisible();
  for (const kind of ["ok", "missing_input", "out_of_range", "extrapolation"]) {
    await expect(page.getByTestId(`validity-${kind}`)).toBeVisible();
  }
  await expect(page.getByTestId("validity-ok")).toContainText(/w porządku: \d+ \(/);
  await expect(page.getByTestId("soft-scores")).toContainText("Po końcu uczenia");
  await expect(page.getByTestId("soft-drift")).toBeVisible();
});

test("a bad lab CSV shows the API message with the line", async ({ page }) => {
  await openWithExample(page);
  await page.getByLabel("Wyniki laboratoryjne (tekst CSV)").fill("sample_time,value\n0,1\n60,abc\n");
  await page.getByRole("button", { name: "Wczytaj wyniki laboratoryjne" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "line 3" })).toContainText("Problem w CSV");
});

for (const width of [1440, 390]) {
  test(`soft sensor page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await loadFitAndRun(page);
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
