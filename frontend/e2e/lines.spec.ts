// Regression test: every uPlot chart must actually draw its series lines (once a redraw() right
// after creation left the x scale unset, so axes and legend showed but no line). Needs the
// `mill_circuit_step_test_seed42` demo dataset (loop hpgr_press has a manual stretch).
import { expect, test, type Page } from "@playwright/test";

const STEP_TEST = "mill_circuit_step_test_seed42";
const LOOP = "hpgr_press";
/** Series colours of the light theme (theme.css --series-1 and --series-3), as RGB. */
const SERIES_RGB = [[0x00, 0x72, 0xb2], [0x00, 0x9e, 0x73]];
/** Minimum number of pixels near a series colour for a line to count as drawn. */
const MIN_LINE_PIXELS = 100;

/** Number of canvases on the page that contain at least MIN_LINE_PIXELS pixels of a series colour. */
async function chartsWithLines(page: Page): Promise<number> {
  return page.evaluate(({ rgb, min }) => {
    const near = (a: number, b: number) => Math.abs(a - b) < 40;
    return [...document.querySelectorAll("canvas")].filter((canvas) => {
      const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
      let hits = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] > 0 && rgb.some(([r, g, b]) => near(data[i], r) && near(data[i + 1], g) && near(data[i + 2], b))) hits++;
      }
      return hits >= min;
    }).length;
  }, { rgb: SERIES_RGB, min: MIN_LINE_PIXELS });
}

test.use({ colorScheme: "light" });

test("tuning window picker draws the PV and OUT lines", async ({ page }) => {
  await page.goto(`/#/d/${STEP_TEST}/loops/${LOOP}/tuning`);
  await expect(page.getByText("Lub wybierz dowolne okno w zapisie")).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await expect.poll(() => chartsWithLines(page)).toBeGreaterThanOrEqual(2);
});

test("loop detail draws its trends and shows the MODE band note", async ({ page }) => {
  await page.goto(`/#/d/${STEP_TEST}/loops/${LOOP}/detail`);
  await page.waitForSelector("canvas", { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await expect.poll(() => chartsWithLines(page)).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".trend-mode-note").first()).toBeVisible();
});
