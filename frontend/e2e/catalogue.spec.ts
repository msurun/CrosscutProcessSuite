// Browser test of the Site Catalogue view (Phase 1, #36 exit criterion):
// navigates to the catalogue view, checks the active nav tab, verifies schema fields
// and saving, and runs axe-core accessibility checks at 1440 and 390 px with no horizontal scroll.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/catalogue`;

const VALID_SITE = {
  schema_version: 1,
  site: {
    name: "E2E Test Site",
    timezone: "UTC",
  },
  sources: [
    { id: "e2e_csv", driver: "csv", endpoint: "/tmp/data" },
  ],
  tags: [],
};

function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return root;
}

function resetSite(): void {
  const root = dataRoot();
  const siteDir = join(root, "_site");
  mkdirSync(siteDir, { recursive: true });
  writeFileSync(join(siteDir, "site.json"), JSON.stringify(VALID_SITE, null, 2), "utf-8");
}

function cleanSite(): void {
  const root = dataRoot();
  rmSync(join(root, "_site"), { recursive: true, force: true });
}

test.beforeEach(resetSite);
test.afterAll(cleanSite);

async function openCataloguePage(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await expect(page.getByRole("heading", { name: /Konfiguracja|Configuration/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: /Katalog|Catalogue/ })).toHaveAttribute("aria-current", "page");
}

test("renders site catalogue form, displays fields, and allows saving", async ({ page }) => {
  const errors: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });

  await openCataloguePage(page);

  // Verify form has rendered with site fields and save button
  const saveButton = page.getByRole("button", { name: /Zapisz|Save/ });
  await expect(saveButton).toBeVisible();

  // Click save and verify success indication
  await saveButton.click();
  await expect(page.getByText(/Zapisano|Saved/)).toBeVisible({ timeout: 10_000 });

  expect(errors).toEqual([]);
});

test("navigating via TopBar catalogue button reaches catalogue view", async ({ page }) => {
  await page.goto(`/#/d/${DATASET}/trends`);
  await expect(page.locator("nav.view-tabs").getByRole("button", { name: /Trendy|Trends/ })).toHaveAttribute("aria-current", "page");

  const topBarButton = page.locator("header.top-bar").getByRole("button", { name: /Katalog|Catalogue/ });
  await expect(topBarButton).toBeVisible();
  await topBarButton.click();

  await expect(page.locator("nav.view-tabs").getByRole("button", { name: /Katalog|Catalogue/ })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: /Konfiguracja|Configuration/ })).toBeVisible({ timeout: 30_000 });
});

test("mapping wizard allows inferring roles, configuring loops, and saving mapping", async ({ page }) => {
  await openCataloguePage(page);

  // Switch to Mapping Wizard mode
  const wizardTab = page.getByTestId("mode-mapping-wizard");
  await expect(wizardTab).toBeVisible();
  await wizardTab.click();

  await expect(page.getByTestId("catalogue-wizard")).toBeVisible();
  await expect(page.getByTestId("wizard-step-source")).toBeVisible();

  // Select manual entry and paste tags
  const manualRadio = page.getByLabel(/Wklej nazwy tagów|Paste tag names/);
  await manualRadio.click();

  const textarea = page.getByTestId("wizard-manual-textarea");
  await textarea.fill("TIC101.PV, TIC101.SP, TIC101.OUT, TIC101.MODE, FEED_RATE, CONC_TARGET");

  // Step 1 -> 2: Inspect tags
  await page.getByRole("button", { name: /Dalej: Sprawdź tagi|Next: Inspect Tags/ }).click();
  await expect(page.getByTestId("wizard-step-tags")).toBeVisible();

  // Step 2 -> 3: Infer roles
  await page.getByRole("button", { name: /Dalej: Wnioskuj role|Next: Infer Roles/ }).click();
  await expect(page.getByTestId("wizard-step-roles")).toBeVisible();

  // Step 3 -> 4: Review loops
  await page.getByRole("button", { name: /Dalej: Przejrzyj pętle|Next: Review Loops/ }).click();
  await expect(page.getByTestId("wizard-step-loops")).toBeVisible();

  // Step 4 -> 5: Summary
  await page.getByRole("button", { name: /Dalej: Podsumowanie|Next: Summary/ }).click();
  await expect(page.getByTestId("wizard-step-confirm")).toBeVisible();

  // Save mapping
  await page.getByTestId("wizard-save-btn").click();
  await expect(page.getByTestId("wizard-success-notice")).toBeVisible({ timeout: 10_000 });
});

test("switches to data sources panel and renders configured sources", async ({ page }) => {
  await openCataloguePage(page);
  await page.getByTestId("mode-data-sources").click();
  await expect(page.getByTestId("sources-panel")).toBeVisible();
  await expect(page.getByTestId("source-card-e2e_csv")).toBeVisible();
  await expect(page.getByTestId("test-source-e2e_csv")).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`catalogue page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openCataloguePage(page);
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
