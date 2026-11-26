// Exercise equipment anomalies against an isolated real FastAPI fixture backend.
// Learning, event feedback and shelving persist through the API; axe checks cover both widths.
import AxeBuilder from "@axe-core/playwright";
import { expect, test as base, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DATASET = "equipment-pump-data";
const OPENED_UTC = "2026-01-01T00:04:00+00:00";
const PAGE_URL = `/#/d/${DATASET}/anomalies`;
const SCRIPT = fileURLToPath(new URL("./support/equipment_anomaly_backend.py", import.meta.url));
const REPOSITORY = fileURLToPath(new URL("../../", import.meta.url));
const PACKAGES = ["anomaly", "api", "artifacts", "connectors", "core", "fuzzy", "gateway",
  "loops", "opcua", "runtime", "sim", "softsensor", "supervisor"];

/** Read the isolated backend address, surfacing startup exceptions instead of a browser timeout. */
function backendAddress(child: ChildProcess): Promise<string> {
  return new Promise((accept, reject) => {
    let output = "";
    let errors = "";
    const timer = setTimeout(() => reject(new Error(`Fixture startup timed out: ${errors}`)), 30_000);
    child.stderr?.on("data", (chunk) => { errors += String(chunk); });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`Fixture backend exited (${code}): ${errors}`));
    });
    child.stdout?.on("data", (chunk) => {
      output += String(chunk);
      const line = output.split(/\r?\n/).find((candidate) => candidate.startsWith("{"));
      if (!line) return;
      clearTimeout(timer);
      accept((JSON.parse(line) as { address: string }).address);
    });
  });
}

/** Stop the fixture before deleting its generated dataset and model files. */
async function stopBackend(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null) return;
  const stopped = new Promise<void>((accept) => child.once("exit", () => accept()));
  child.kill();
  await stopped;
}

const test = base.extend<{ equipmentBackend: string }>({
  equipmentBackend: async ({ request }, use) => {
    const root = mkdtempSync(join(tmpdir(), "equipment-anomalies-"));
    const pythonPath = [REPOSITORY, ...PACKAGES.map((name) => resolve(REPOSITORY, name, "src"))];
    const child = spawn(process.env.E2E_PYTHON ?? "python", [SCRIPT, root], {
      env: { ...process.env, PYTHONPATH: pythonPath.join(delimiter) }, stdio: "pipe",
    });
    try {
      const address = await backendAddress(child);
      await expect.poll(async () => {
        try { return (await request.get(`${address}/health`)).ok(); }
        catch { return false; }
      }).toBe(true);
      await use(address);
    } finally {
      await stopBackend(child);
      rmSync(root, { recursive: true, force: true });
    }
  },
});

test.use({ locale: "en-US" });

/** Forward API traffic to the fixture while retaining the shared Vite frontend. */
async function openEquipment(page: Page, address: string): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const original = new URL(route.request().url());
    const response = await route.fetch({ url: `${address}${original.pathname.slice(4)}${original.search}` });
    await route.fulfill({ response });
  });
  await page.goto(PAGE_URL);
  await expect(page.getByTestId("equipment-pump")).toBeVisible();
}

test("equipment shows its area, loop and signal contributions, history and Advanced detector", async ({ page, equipmentBackend }) => {
  await openEquipment(page, equipmentBackend);
  const pump = page.getByTestId("equipment-pump");
  await expect(pump).toContainText("Feed pump");
  await expect(page.getByTestId("equipment-anomalies-page")).toContainText("Grinding");
  await expect(pump).toContainText("flow-loop");
  await expect(pump).toContainText("current");
  await expect(pump.getByTestId(`outcome-${OPENED_UTC}`)).toBeVisible();
  await expect(pump.getByTestId("outcome-2026-01-01T00:01:00+00:00")).toBeVisible();
  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  await expect(page.getByTestId("anomaly-empty")).toBeVisible();
  await page.getByRole("button", { name: "Equipment", exact: true }).click();
  await expect(pump).toBeVisible();
});

test("learning uses the chosen dataset and proposed UTC window", async ({ page, equipmentBackend }) => {
  await openEquipment(page, equipmentBackend);
  const pump = page.getByTestId("equipment-pump");
  await pump.getByRole("button", { name: "Learn", exact: true }).click();
  await page.getByTestId("learn-dataset").selectOption(DATASET);
  await page.getByTestId("learn-start").fill("2026-01-01T00:00:00Z");
  await page.getByTestId("learn-end").fill("2026-01-01T00:04:00Z");
  const learned = page.waitForResponse((response) => response.url().endsWith(`/equipment/pump/learn`));
  await page.getByTestId("learn-submit").click();
  const response = await learned;
  expect(response.ok()).toBe(true);
  expect((await response.json()).status).toBe("learned");
  await expect(pump).toContainText("Learned");
  const models = await page.request.get(`${equipmentBackend}/equipment/models`);
  expect((await models.json())[0].windows[0][1]).toBeLessThanOrEqual(240);
});

test("operator feedback and shelving survive a reload", async ({ page, equipmentBackend }) => {
  await openEquipment(page, equipmentBackend);
  const pump = page.getByTestId("equipment-pump");
  const outcome = pump.getByTestId(`outcome-${OPENED_UTC}`);
  const savedOutcome = page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().endsWith("/pump/outcome"));
  await outcome.selectOption("maintenance_raised");
  expect((await savedOutcome).ok()).toBe(true);
  await expect(outcome).toHaveValue("maintenance_raised");
  await pump.getByTestId("shelve-until").fill("2035-01-01T12:00");
  await pump.getByTestId("shelve-submit").click();
  await expect(pump.getByTestId("unshelve")).toBeVisible();
  await page.reload();
  await expect(pump.getByTestId(`outcome-${OPENED_UTC}`)).toHaveValue("maintenance_raised");
  await pump.getByTestId("unshelve").click();
  await expect(pump.getByTestId("shelve-submit")).toBeVisible();
  const rows = await page.request.get(`${equipmentBackend}/equipment/anomalies`);
  expect((await rows.json())[0].shelved_until_utc).toBeNull();
});

for (const width of [1440, 390]) {
  test(`equipment anomalies have no serious axe violations or horizontal scroll @${width}`, async ({ page, equipmentBackend }) => {
    await page.setViewportSize({ width, height: 900 });
    await openEquipment(page, equipmentBackend);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical")
      .map((item) => item.id)).toEqual([]);
  });
}
