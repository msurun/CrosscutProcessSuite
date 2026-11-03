// Playwright end‑to‑end tests for the Runtime view (Phase #44).
// Sets up a minimal site with an OPC‑UA source, creates a KPI job,
// checks its lifecycle, and runs axe accessibility checks.

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/runtime`;

function dataRoot(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) {
    throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  }
  return root;
}

function opcuaEndpoint(): string {
  const ep = process.env.E2E_OPCUA_ENDPOINT;
  if (!ep) {
    throw new Error(
      "Set E2E_OPCUA_ENDPOINT to the OPC‑UA endpoint for the runtime test."
    );
  }
  return ep;
}

/** Write a minimal site.json for the runtime view and clean old runtime jobs. */
function resetSite(): void {
  const root = dataRoot();
  const siteDir = join(root, "_site");
  mkdirSync(siteDir, { recursive: true });

  const siteJson = {
    schema_version: 1,
    site: { name: "E2E Runtime", timezone: "UTC" },
    sources: [
      {
        id: "wb_sim",
        driver: "opcua",
        endpoint: opcuaEndpoint(),
        options: {},
      },
    ],
    tags: [
      {
        id: "sim.wb.top_comp",
        source: "wb_sim",
        address: "nsu=urn:crosscut:sim;s=sim.wb.top_comp",
      },
      {
        id: "sim.wb.top_comp_sp",
        source: "wb_sim",
        address: "nsu=urn:crosscut:sim;s=sim.wb.top_comp_sp",
      },
      {
        id: "sim.wb.reflux",
        source: "wb_sim",
        address: "nsu=urn:crosscut:sim;s=sim.wb.reflux",
      },
      {
        id: "sim.wb.top_comp_mode",
        source: "wb_sim",
        address: "nsu=urn:crosscut:sim;s=sim.wb.top_comp_mode",
      },
    ],
    loops: [
      {
        id: "WB.TOP",
        pv: "sim.wb.top_comp",
        sp: "sim.wb.top_comp_sp",
        out: "sim.wb.reflux",
        mode: "sim.wb.top_comp_mode",
        out_limits: { min: 0, max: 100 },
      },
    ],
  };

  writeFileSync(
    join(siteDir, "site.json"),
    JSON.stringify(siteJson, null, 2),
    "utf-8"
  );

  // Remove any stale runtime job file.
  rmSync(join(root, "_runtime", "jobs.json"), { force: true });
}

/** Remove the temporary site and any runtime jobs created during the tests. */
function cleanAll(): void {
  const root = dataRoot();
  rmSync(join(root, "_site"), { recursive: true, force: true });
  rmSync(join(root, "_runtime", "jobs.json"), { force: true });
}

/** Navigate to the runtime view and assert the nav tab is active. */
async function openRuntimePage(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await expect(page.getByRole("heading", { name: /Runtime|Runtime/ })).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    page.locator("nav.view-tabs").getByRole("button", { name: /Runtime|Runtime/ })
  ).toHaveAttribute("aria-current", "page");
}

/** Apply the same timeout to all tests – the main flow needs up to 150 s. */
test.setTimeout(150_000);
test.describe.configure({ mode: "serial" });

test.beforeAll(resetSite);
test.afterAll(cleanAll);

test("runtime page can create, stop, start a KPI job and shows KPI info", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });

  await openRuntimePage(page);

  // Fill the new‑job form.
  await page.getByTestId("runtime-form-id").fill("kpi-e2e");
  await page.getByTestId("runtime-form-kind").selectOption("loop_kpi");
  await page.getByTestId("runtime-form-source").fill("wb_sim");
  await page.getByTestId("runtime-form-targets").fill("WB.TOP");
  await page.getByTestId("runtime-form-period").fill("0.5");
  await page.getByTestId("runtime-form-window").fill("60");

  // Create the job and wait for its row to appear.
  await page.getByTestId("runtime-create").click();
  const jobRow = page.getByTestId("runtime-job-kpi-e2e");
  await expect(jobRow).toBeVisible({ timeout: 30_000 });

  // Stop then start the job.
  await page.getByTestId("runtime-stop-kpi-e2e").click();
  await expect(page.getByTestId("runtime-start-kpi-e2e")).toBeVisible();
  await page.getByTestId("runtime-start-kpi-e2e").click();

  // Service status must indicate that the runtime is active.
  await expect(page.getByTestId("runtime-service-status")).toContainText(
    /działa|running/i
  );

  const kpiCell = jobRow.locator("td").nth(11);
  const samplesCell = jobRow.locator("td").nth(10);

  // Wait until KPI information appears and the samples count is > 0.
  await expect
    .poll(async () => (await kpiCell.textContent()) ?? "", { timeout: 120_000, intervals: [1000] })
    .toMatch(/WB\.TOP: (manual|saturated|oscillating|poor_performance|ok)/);

  await expect
    .poll(async () => Number((await samplesCell.textContent()) ?? "0"), { timeout: 120_000, intervals: [1000] })
    .toBeGreaterThan(0);

  expect(errors).toEqual([]);
});

for (const width of [1440, 390] as const) {
  test(`runtime page has no axe violations and no horizontal scroll @${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(PAGE_URL);
    await expect(page.getByTestId("runtime-page")).toBeVisible({
      timeout: 30_000,
    });

    if (width === 390) {
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth
      );
      expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    }

    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical"
    );
    expect(
      bad.map(
        (v) =>
          `${v.id}: ${v.nodes
            .slice(0, 3)
            .map((n) => n.target.join(" "))
            .join(" | ")}`
      )
    ).toEqual([]);
  });
}
