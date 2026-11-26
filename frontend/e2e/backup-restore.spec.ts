// E2E of backup and restore (#167): create a saved trend chart, download a backup from the
// Administration > Backup page, rename the chart, upload the backup, read the dry run, restore, and
// see the original chart again. Then axe-check the page. Runs in English, auth off (local admin).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const DATASET = "mill_circuit_stiction_seed42";
const ORIGINAL = "Backup original";
const CHANGED = "Backup changed";
const DRAFT = {
  name: ORIGINAL,
  shared: false,
  series: [{ source: "demo", tag: "TAG_A", axis: "a1" }],
  axes: [{ id: "a1", side: "left" }],
  window: { kind: "relative", last_s: 3600 },
};

test.use({ locale: "en-US" });

/** The names of the saved charts the API lists. */
async function chartNames(page: Page): Promise<string[]> {
  const response = await page.request.get("/api/trends/charts");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { charts: { name: string }[] }).charts.map((c) => c.name);
}

test("backup, change, restore: the original configuration returns", async ({ page }) => {
  const created = await page.request.post("/api/trends/charts", { data: DRAFT });
  expect(created.ok(), await created.text()).toBeTruthy();
  const chart = (await created.json()) as { id: string };

  await page.goto(`/#/d/${DATASET}/backup`);
  await expect(page.getByRole("heading", { name: "Backup and restore" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Datasets and Parquet history")).toBeVisible();

  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download backup" }).click();
  const file = join(mkdtempSync(join(tmpdir(), "cc-backup-")), "backup.zip");
  await (await downloading).saveAs(file);

  const changed = await page.request.put(`/api/trends/charts/${chart.id}`, { data: { ...DRAFT, name: CHANGED } });
  expect(changed.ok(), await changed.text()).toBeTruthy();
  expect(await chartNames(page)).toContain(CHANGED);

  await page.getByLabel("Backup file (.zip)").setInputFiles(file);
  await page.getByRole("button", { name: "Check backup (dry run)" }).click();
  const report = page.getByRole("region", { name: "Dry-run report" });
  await expect(report.getByText("The backup is valid.")).toBeVisible();
  await expect(report.getByRole("row", { name: new RegExp(`${chart.id}.json Replace`) })).toBeVisible();
  await expect(report.getByText("Enter these secrets again")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);

  await page.getByLabel(/I understand that the files listed above/).check();
  await page.getByRole("button", { name: "Restore now" }).click();
  await expect(page.getByText(/Backup restored\./)).toBeVisible();

  const names = await chartNames(page);
  expect(names).toContain(ORIGINAL);
  expect(names).not.toContain(CHANGED);
  await page.request.delete(`/api/trends/charts/${chart.id}`);
});

test("a damaged backup is refused in the dry run", async ({ page }) => {
  await page.goto(`/#/d/${DATASET}/backup`);
  await page.getByLabel("Backup file (.zip)").setInputFiles({
    name: "bad.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("this is not a zip"),
  });
  await page.getByRole("button", { name: "Check backup (dry run)" }).click();
  await expect(page.getByText("This backup cannot be restored:")).toBeVisible();
  await expect(page.getByRole("button", { name: "Restore now" })).toHaveCount(0);
});
