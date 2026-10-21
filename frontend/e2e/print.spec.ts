// Print layout check: with print media emulated the navigation chrome is gone, charts are still
// drawn, tables fit the page width and nothing needs horizontal scrolling. With E2E_SHOTS set the
// pages are also saved as PDF for a visual check.
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const STICTION = "mill_circuit_stiction_seed42";
const LOOP = "hpgr_press";
/** A4 content width in CSS px at 96 dpi minus the 12 mm margins, with a little slack. */
const PRINT_WIDTH_PX = 760;

/** Walks the valve test flow: create the plan, tick the checklist and show the operator procedure. */
async function openProcedure(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Utwórz plan" }).click();
  await expect(page.getByRole("checkbox")).toHaveCount(3);
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await page.getByRole("button", { name: "Pokaż procedurę" }).click();
  await expect(page.getByText("Procedura operatora")).toBeVisible();
}

interface PrintPage {
  name: string;
  hash: string;
  heading: RegExp;
  canvases: boolean;
  prepare?: (page: Page) => Promise<void>;
}

const PAGES: PrintPage[] = [
  { name: "valve-procedure", hash: `#/d/${STICTION}/loops/${LOOP}/valve`, heading: /Test skokowy zaworu/, canvases: false, prepare: openProcedure },
  { name: "loop-detail", hash: `#/d/${STICTION}/loops/${LOOP}/detail`, heading: /hpgr_press/, canvases: true },
];

/** Count of elements matching `selector` that are rendered (non-zero box) in the current media. */
async function visibleCount(page: Page, selector: string): Promise<number> {
  return page.locator(selector).evaluateAll((nodes) => nodes.filter((n) => (n as HTMLElement).offsetParent !== null).length);
}

for (const pageSpec of PAGES) {
  test(`print layout: ${pageSpec.name}`, async ({ page }) => {
    await page.setViewportSize({ width: PRINT_WIDTH_PX, height: 1000 });
    await page.goto(`/${pageSpec.hash}`);
    await expect(page.getByText(pageSpec.heading).first()).toBeVisible({ timeout: 30_000 });
    if (pageSpec.canvases) await page.waitForSelector("canvas", { timeout: 30_000 });
    await pageSpec.prepare?.(page);
    await page.waitForLoadState("networkidle");
    await page.emulateMedia({ media: "print" });
    await page.waitForTimeout(800);

    for (const chrome of [".top-bar", ".sidebar", ".view-tabs", ".stepper", ".breadcrumb", ".context-bar"]) {
      expect(await visibleCount(page, chrome), `${chrome} hidden in print`).toBe(0);
    }
    if (pageSpec.canvases) expect(await visibleCount(page, "canvas")).toBeGreaterThanOrEqual(2);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal overflow in print").toBeLessThanOrEqual(0);
    const wideTables = await page.locator("table").evaluateAll(
      (tables) => tables.filter((t) => t.getBoundingClientRect().right > window.innerWidth + 1).length,
    );
    expect(wideTables, "tables cut at the right edge").toBe(0);
    if (process.env.E2E_SHOTS) {
      await page.pdf({ path: join(process.env.E2E_SHOTS, `print-${pageSpec.name}.pdf`), format: "A4", margin: { top: "12mm", bottom: "12mm", left: "12mm", right: "12mm" } });
      await page.screenshot({ path: join(process.env.E2E_SHOTS, `print-${pageSpec.name}.png`), fullPage: true });
    }
  });
}
