// Browser test of the Import view (Polish): upload a synthetic level step test (semicolon, decimal
// comma, 2 s samples, MAN; made by e2e/support/make_step_csv.py), see the preview and the pre-filled
// mapping, check it (ready, dry run slope close to the true one), create the dataset e2e_import_<n>
// and open it in the tuning view. Also axe (serious/critical none) at 1440 and 390 px and no
// horizontal scroll at 390. The API writes only the new dataset folder under E2E_DATA_ROOT; the spec
// deletes that folder after each test and nothing else. E2E_PYTHON runs the CSV script (needs numpy).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const START_URL = "/#/d/level_integrating_demo/import";
const SCRIPT = fileURLToPath(new URL("./support/make_step_csv.py", import.meta.url));
const TRUE_SLOPE = 0.001;

let csvPath = "";
let created = "";

/** The data root served by the API under test. */
function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.beforeAll(() => {
  csvPath = join(mkdtempSync(join(tmpdir(), "import-step-")), "step.csv");
  execFileSync(process.env.E2E_PYTHON ?? "python", [SCRIPT, csvPath]);
});

// Removes the dataset folder this test created (a direct child of the data root), nothing else.
test.afterEach(() => {
  const target = resolve(dataRoot(), created);
  if (created !== "" && dirname(target) === resolve(dataRoot())) rmSync(target, { recursive: true, force: true });
  created = "";
});
test.setTimeout(120_000);

/** Chooses the file and waits for the preview with the mapping pre-filled. */
async function chooseFile(page: Page): Promise<void> {
  await page.goto(START_URL);
  await expect(page.getByRole("note").first()).toContainText("Nic nie jest wysyłane do instalacji");
  await page.getByLabel("Plik CSV z historiana").setInputFiles(csvPath);
  await expect(page.getByTestId("import-source")).toContainText("Wybrano: step.csv");
  await expect(page.getByLabel("Zmienna procesowa (poziom)")).toHaveValue("LIC1.PV");
}

/** Runs the check and waits for the result panel. */
async function runCheck(page: Page): Promise<void> {
  await page.getByRole("button", { name: "3. Sprawdź zapis" }).click();
  await expect(page.getByTestId("import-result")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("[data-testid=import-chart] canvas").first()).toBeVisible();
}

test("upload, preview, check, create and open the tuning view", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("response", (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  await chooseFile(page);
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: "Import danych" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByLabel("Separator kolumn")).toHaveValue(";");
  await expect(page.getByLabel("Znak dziesiętny")).toHaveValue("comma");
  await expect(page.getByLabel("Wyjście regulatora (zawór)")).toHaveValue("LIC1.OUT");
  await expect(page.getByLabel("Tryb, ręczny lub auto (opcjonalnie)")).toHaveValue("LIC1.MODE");
  await expect(page.getByRole("table")).toContainText("LIC1.PV");
  await runCheck(page);
  await expect(page.getByTestId("import-result").getByRole("status")).toContainText("Gotowy");
  await expect(page.getByText("Nie znaleziono problemów.")).toBeVisible();
  const slopeText = await page.getByText("Nachylenie rampy (PV na sekundę na % OUT)").locator("xpath=following-sibling::dd").innerText();
  const slope = Number(slopeText.replace(",", "."));
  expect(Math.abs(slope - TRUE_SLOPE) / TRUE_SLOPE, `slope ${slopeText}`).toBeLessThan(0.15);
  await expect(page.getByText(/\(zakres [\d,]+ do [\d,]+ s\)/)).toBeVisible();
  await expect(page.getByText(/górnej granicy zakresu czasu martwego/)).toBeVisible();
  await expect(page.getByText(/UTC/).first()).toBeVisible();
  await expect(page.getByText(/Układ: szeroki/)).toBeVisible();
  await expect(page.getByText(/layout wide/)).toHaveCount(0);

  created = `e2e_import_${Date.now()}_${info.workerIndex}`;
  await page.getByLabel("Identyfikator zbioru danych").fill(created);
  await page.getByRole("button", { name: "Utwórz zbiór danych" }).click();
  await expect(page.getByTestId("import-done")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Otwórz w Strojeniu" }).click();
  await expect(page.getByRole("heading", { name: "2. Sprawdź model" })).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(new RegExp(`/d/${created}/loops/LIC1/tuning`));
  await expect(page.getByText("Nachylenie rampy").first()).toBeVisible();
  await expect(page.getByText(/Propozycja \(reguła SIMC dla procesu całkującego\)/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("an existing dataset id is refused with a plain message", async ({ page }) => {
  await chooseFile(page);
  await runCheck(page);
  await page.getByLabel("Identyfikator zbioru danych").fill("level_integrating_demo");
  await page.getByRole("button", { name: "Utwórz zbiór danych" }).click();
  await expect(page.getByText("Zbiór danych o tym identyfikatorze już istnieje")).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`import view has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await chooseFile(page);
    await runCheck(page);
    await page.getByLabel("Identyfikator zbioru danych").fill("a b");
    await expect(page.getByRole("alert")).toContainText("Używaj tylko liter");
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
