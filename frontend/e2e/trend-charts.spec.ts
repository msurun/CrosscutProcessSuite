// E2E of the saved trend charts flow: build a two-axis chart, save it, see its panes render,
// duplicate and delete the copy, then axe-check the Saved charts view. Runs in English.
// Needs the demo dataset `mill_circuit_stiction_seed42`.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_stiction_seed42";
const CHART_NAME = "E2E two axes";

test.use({ locale: "en-US" });

/** Adds the first tag of the first unit group and then the first tag of a group with another unit. */
async function addTagsWithDifferentUnits(page: Page): Promise<void> {
  const picker = page.getByRole("region", { name: "Add tags" });
  const headings = picker.locator("h4");
  await expect(headings.first()).toBeVisible({ timeout: 30_000 });
  const unitOf = async (i: number) => ((await headings.nth(i).innerText()).split("·").pop() ?? "").trim();
  const first = await unitOf(0);
  let other = -1;
  for (let i = 1; i < (await headings.count()); i++) {
    if ((await unitOf(i)) !== first) { other = i; break; }
  }
  expect(other, "demo dataset has tags with two different units").toBeGreaterThan(0);
  const addIn = (i: number) => headings.nth(i).locator("xpath=following-sibling::ul[1]").getByRole("button", { name: /^Add/ }).first();
  await addIn(0).click();
  await addIn(other).click();
}

test("saved trend chart: build, save, duplicate, delete, axe", async ({ page }) => {
  await page.goto(`/#/d/${DATASET}/trends`);
  const modes = page.getByRole("group", { name: "Trends mode" });
  await modes.getByRole("button", { name: "Saved charts" }).click();
  await expect(modes.getByRole("button", { name: "Saved charts" })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "New chart", exact: true }).click();
  await page.getByLabel("Chart name").fill(CHART_NAME);
  await addTagsWithDifferentUnits(page);
  await expect(page.getByRole("table", { name: "Axes" }).locator("tbody tr")).toHaveCount(2);

  await page.getByRole("button", { name: "8h", exact: true }).click();
  await expect(page.getByRole("button", { name: "8h", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Save chart" }).click();

  const panel = page.getByRole("complementary").or(page.locator("body"));
  await expect(panel.getByText("My charts")).toBeVisible();
  await expect(page.getByRole("button", { name: `Open ${CHART_NAME}`, exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: CHART_NAME }).locator("canvas").first()).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: `Duplicate chart ${CHART_NAME}`, exact: true }).click();
  const copy = page.getByRole("button", { name: /^Open E2E two axes .+/ });
  await expect(copy).toHaveCount(1, { timeout: 15_000 });
  const copyName = (await copy.getAttribute("aria-label"))!.replace(/^Open /, "");
  await page.getByRole("button", { name: `Delete chart ${copyName}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete chart" });
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: `Open ${copyName}`, exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: `Open ${CHART_NAME}`, exact: true })).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);

  // Cleanup so reruns start clean.
  await page.getByRole("button", { name: `Delete chart ${CHART_NAME}`, exact: true }).click();
  await page.getByRole("dialog", { name: "Delete chart" }).getByRole("button", { name: "Confirm" }).click();
});
