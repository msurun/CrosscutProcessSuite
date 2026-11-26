// Exercise the Overview start page against an isolated real FastAPI fixture backend.
// Existing synthetic equipment findings drive the tiles; axe checks cover desktop and mobile.
import AxeBuilder from "@axe-core/playwright";
import { expect, test as base, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";


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
async function openOverview(page: Page, address: string): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const original = new URL(route.request().url());
    const response = await route.fetch({ url: `${address}${original.pathname.slice(4)}${original.search}` });
    await route.fulfill({ response });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
}

test("Overview is the start page and links findings to their full views", async ({ page, equipmentBackend }) => {
  await openOverview(page, equipmentBackend);
  await expect(page.getByTestId("overview-worklist")).toContainText("flow-loop");
  await expect(page.getByTestId("overview-anomalies")).toContainText("pump");
  await expect(page.getByTestId("overview-worklist").getByRole("link").first()).toHaveAttribute("href", /loops/);
  await expect(page.getByTestId("overview-anomalies").getByRole("link").first()).toHaveAttribute("href", /anomalies/);
  await page.getByTestId("overview-worklist").getByRole("link").first().click();
  await expect(page.getByTestId("live-loops")).toContainText("flow-loop");
  await page.getByRole("button", { name: "Trends", exact: true }).click();
  await expect(page).toHaveURL(/\/trends$/);
});

test("an unavailable source leaves other Overview tiles usable", async ({ page, equipmentBackend }) => {
  await page.route("**/api/**", async (route) => {
    const original = new URL(route.request().url());
    if (original.pathname.endsWith("/controllers")) {
      await route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"unavailable"}' });
      return;
    }
    const response = await route.fetch({ url: `${equipmentBackend}${original.pathname.slice(4)}${original.search}` });
    await route.fulfill({ response });
  });
  await page.goto("/");
  await expect(page.getByTestId("overview-controllers")).toContainText("Not available");
  await expect(page.getByTestId("overview-worklist")).toContainText("flow-loop");
});

for (const width of [1440, 390]) {
  test(`Overview has no serious axe violations or horizontal scroll @${width}`, async ({ page, equipmentBackend }) => {
    await page.setViewportSize({ width, height: 900 });
    await openOverview(page, equipmentBackend);
    await expect(page.getByTestId("overview-anomalies")).toContainText("pump");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations.filter((item) => item.impact === "serious" || item.impact === "critical")
      .map((item) => item.id)).toEqual([]);
  });
}



