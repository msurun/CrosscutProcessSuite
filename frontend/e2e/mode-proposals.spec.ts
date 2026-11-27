// Browser test of the operating-mode and equipment-group proposals (#145, PRODUCT 3.1 step 2):
// the proposal route and the site document are mocked with page.route, the engineer edits a
// threshold and accepts one mode, the saved site document carries it, then axe (serious/critical
// none) at 1440 and 390 px with no horizontal scroll.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/catalogue`;
const PROPOSE = "Zaproponuj z historii";

const EVIDENCE = {
  kind: "bimodal_gap",
  share: 0.31,
  thresholds: { threshold: 3 },
  windows: [[0, 600]],
  events: 3,
  detail: "PMP7_CURR splits into two clusters (separation 0.98)",
};
const PROPOSALS = {
  dataset: DATASET,
  equipment: [
    {
      id: "PMP7",
      confidence: "high",
      evidence: { ...EVIDENCE, kind: "co_switching" },
      entry: { id: "PMP7", name: "PMP7", level: "equipment", tags: ["PMP7_RUN", "PMP7_CURR"] },
    },
  ],
  modes: [
    {
      id: "PMP7_stopped",
      confidence: "high",
      evidence: EVIDENCE,
      scope_new: true,
      entry: {
        id: "PMP7_stopped",
        name: "PMP7 stopped",
        scope: "PMP7",
        condition: { match: "all", clauses: [{ tag: "PMP7_CURR", op: "<=", value: 3 }] },
      },
    },
  ],
};
const SITE = { schema_version: 1, site: { name: "E2E Test Site", timezone: "UTC" }, tags: [] };

/** Mocks the proposal route and the site document; returns the bodies the page PUT. */
async function mockBackend(page: Page): Promise<unknown[]> {
  const saved: unknown[] = [];
  await page.route("**/api/datasets/*/catalogue/proposals/modes", (route: Route) => route.fulfill({ json: PROPOSALS }));
  await page.route("**/api/site", (route: Route) => {
    if (route.request().method() === "PUT") {
      saved.push(route.request().postDataJSON());
      return route.fulfill({ json: SITE });
    }
    return route.fulfill({ json: SITE });
  });
  return saved;
}

async function openProposals(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await page.getByTestId("mode-proposals").click();
  await page.getByRole("button", { name: PROPOSE }).click();
  await expect(page.getByText("PMP7 stopped", { exact: true })).toBeVisible({ timeout: 30_000 });
}

test("edit a threshold, accept the mode and see it in the saved site document", async ({ page }) => {
  const saved = await mockBackend(page);
  await openProposals(page);
  await expect(page.getByRole("heading", { name: "Grupy sprzętu" })).toBeVisible();

  await page.getByLabel("Wartość PMP7_CURR <=").fill("4.5");
  await page.getByRole("button", { name: "Akceptuj PMP7 stopped" }).click();
  await expect(page.getByText("Zapisano PMP7_stopped w katalogu.")).toBeVisible();

  expect(saved).toHaveLength(1);
  const doc = saved[0] as { modes: { condition: { clauses: { value: number }[] } }[]; equipment: { id: string }[] };
  expect(doc.modes[0].condition.clauses[0].value).toBe(4.5);
  expect(doc.equipment.map((e) => e.id)).toContain("PMP7");
});

test("rejecting a group removes it without saving", async ({ page }) => {
  const saved = await mockBackend(page);
  await openProposals(page);
  await page.getByRole("button", { name: "Odrzuć PMP7", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Grupy sprzętu" })).toHaveCount(0);
  expect(saved).toHaveLength(0);
});

for (const width of [1440, 390]) {
  test(`mode proposals have no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockBackend(page);
    await openProposals(page);
    await page.locator("details summary").first().click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    const axe = await new AxeBuilder({ page }).analyze();
    const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
}
