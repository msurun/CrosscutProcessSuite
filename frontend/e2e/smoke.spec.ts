// Smoke test of every main view in the real browser, in Polish at 1440 and 390 px width.
// Per view: renders without console errors, shows its heading, has no horizontal page scroll at
// 390 px, and axe-core finds no serious or critical violation. Screenshots go to E2E_SHOTS if set.
// Needs the demo datasets `mill_circuit_stiction_seed42` and `mill_circuit_step_test_seed42`.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const STICTION = "mill_circuit_stiction_seed42";
const STEP_TEST = "mill_circuit_step_test_seed42";
const LOOP = "hpgr_press";

interface View {
  name: string;
  hash: string;
  heading: RegExp;
  prepare?: (page: Page) => Promise<void>;
}

const VIEWS: View[] = [
  { name: "trends", hash: `#/d/${STICTION}/trends`, heading: /Trendy/ },
  { name: "loops-overview", hash: `#/d/${STICTION}/loops`, heading: /Pętle regulacji/ },
  { name: "loop-detail", hash: `#/d/${STICTION}/loops/${LOOP}/detail`, heading: /hpgr_press/ },
  { name: "knowledge-editor", hash: `#/d/${STICTION}/loops/${LOOP}/detail`, heading: /Dane pętli/,
    prepare: async (page) => { await page.getByText("Dane pętli").first().click(); } },
  { name: "tuning-step1", hash: `#/d/${STEP_TEST}/loops/${LOOP}/tuning`, heading: /Raport strojenia/ },
  { name: "valve-test", hash: `#/d/${STICTION}/loops/${LOOP}/valve`, heading: /Test skokowy zaworu/ },
  { name: "benefit", hash: `#/d/${STICTION}/loops/${LOOP}/benefit`, heading: /Raport korzyści/ },
  { name: "fuzzy-variables", hash: `#/d/${STICTION}/fuzzy`, heading: /Fuzzy Studio/ },
  ...["Reguły", "Odtworzenie", "Test wsteczny"].map((tab): View => ({
    name: `fuzzy-${tab.replace(/\s/g, "-")}`, hash: `#/d/${STICTION}/fuzzy`, heading: /Fuzzy Studio/,
    prepare: async (page) => { await page.getByRole("tab", { name: tab }).click(); },
  })),
];

for (const width of [1440, 390]) {
  for (const view of VIEWS) {
    test(`${view.name} @${width}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
      page.on("response", (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/${view.hash}`);
      await expect(page.getByRole("heading", { name: view.heading }).or(page.getByText(view.heading)).first()).toBeVisible({ timeout: 30_000 });
      await view.prepare?.(page);
      await page.waitForLoadState("networkidle");
      if (width === 390) {
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
      }
      if (width === 1440 && process.env.E2E_SHOTS) {
        await page.screenshot({ path: join(process.env.E2E_SHOTS, `${view.name}.png`), fullPage: true });
      }
      const axe = await new AxeBuilder({ page }).analyze();
      const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
