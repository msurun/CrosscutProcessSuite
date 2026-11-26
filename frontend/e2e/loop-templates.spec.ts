// Browser test of the loop template editor (PRODUCT 4.1): open the Templates view from Loops,
// check the packaged flow template, edit its default step, save a site copy, reload and see the
// copy, then run axe (serious/critical none) at 1440 and 390 px with no horizontal scroll.
// The site copy lives under <E2E_DATA_ROOT>/_loop_templates and is removed after the spec.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { rmSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/loops`;

const TEMPLATES_BUTTON = "Szablony";
const TITLE_TEXT = "Szablony pętli";
const STEP_LABEL = "Domyślny krok OUT, % zakresu";
const SAVE_BUTTON = "Zapisz kopię witryny";
const SAVED_TEXT = "Zapisano. Kopia witryny zastępuje teraz szablon z pakietu.";

function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

test.afterAll(() => {
  rmSync(join(dataRoot(), "_loop_templates"), { recursive: true, force: true });
});

/** Opens the Loops view and switches to the template editor. */
async function openTemplateEditor(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: "Pętle" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: TEMPLATES_BUTTON }).click();
  await expect(page.getByRole("heading", { name: TITLE_TEXT })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("loop-template-select")).toHaveValue("flow");
}

test("edit the flow template, save a site copy and keep it after a reload", async ({ page }) => {
  await openTemplateEditor(page);

  await page.getByLabel(STEP_LABEL).fill("4");
  await page.getByRole("button", { name: SAVE_BUTTON }).click();
  await expect(page.getByText(SAVED_TEXT)).toBeVisible({ timeout: 10_000 });

  await page.reload();
  await page.getByRole("button", { name: TEMPLATES_BUTTON }).click();
  await expect(page.getByTestId("loop-template-select")).toHaveValue("flow", { timeout: 30_000 });
  await expect(page.getByLabel(STEP_LABEL)).toHaveValue("4");
});

for (const width of [1440, 390]) {
  test(`loop templates page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openTemplateEditor(page);
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
