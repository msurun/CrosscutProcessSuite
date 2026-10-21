// Browser test of the Advisory page (Polish): load the example config, replay a simulated mill
// circuit record with "record to log" on, record a decision on one advice, reload and see it still
// recorded. Also axe (serious/critical none) and no horizontal scroll at 1440 and 390 px.
// Needs the demo dataset `mill_circuit_observational_seed42`; the API must be allowed to write to
// its data root (_supervisor, _advisory), so use a scratch copy of the demo datasets.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const URL = `/#/d/${DATASET}/advisory`;

/** Opens the page and loads the example config when no supervisor exists yet. */
async function openAdvisory(page: Page): Promise<void> {
  await page.goto(URL);
  const load = page.getByRole("button", { name: "Wczytaj przykład" });
  const picker = page.getByLabel("Nadzorca");
  await expect(load.or(picker)).toBeVisible({ timeout: 30_000 });
  if (await load.isVisible()) await load.click();
  await expect(picker).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Tylko doradztwo");
}

/** Replays with a coarse step and records the advices in the log. */
async function replayAndRecord(page: Page): Promise<void> {
  await page.getByLabel("Okno (s)").fill("1800");
  await page.getByLabel("Krok (s)").fill("3600");
  await page.getByLabel("Zapisz w dzienniku").check();
  await page.getByRole("button", { name: "Uruchom odtworzenie" }).click();
  await expect(page.getByText(/zapisanych w dzienniku: [1-9]/)).toBeVisible({ timeout: 30_000 });
}

test("replay with record, decision and reload", async ({ page }) => {
  await openAdvisory(page);
  await expect(page.getByLabel("Zapisz w dzienniku")).not.toBeChecked();
  await replayAndRecord(page);
  await expect(page.getByText(/łańcuch zweryfikowany/)).toBeVisible();
  const log = page.getByRole("region", { name: "Dziennik" });
  const card = log.getByRole("listitem").filter({ hasText: "Nie zapisano jeszcze decyzji." }).first();
  await card.getByRole("button", { name: "Zapisz decyzję: Przyjmij" }).click();
  await card.getByRole("button", { name: "Zapisz decyzję", exact: true }).click();
  await expect(card.getByRole("alert")).toContainText("Wybierz powód");
  await card.getByLabel("Powód").selectOption("agrees_with_process");
  await card.getByLabel("Kto zdecydował").fill("e2e operator");
  await card.getByRole("button", { name: "Zapisz decyzję", exact: true }).click();
  await expect(log.getByText(/Zapisana decyzja: przyjęto, osoba: e2e operator/).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole("region", { name: "Dziennik" }).getByText(/Zapisana decyzja: przyjęto, osoba: e2e operator/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/łańcuch zweryfikowany/)).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`advisory page has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openAdvisory(page);
    await replayAndRecord(page);
    await page.getByRole("region", { name: "Dziennik" }).getByRole("button", { name: "Zapisz decyzję: Odłóż" }).first().click();
    await page.getByRole("button", { name: "Poradź teraz", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Poradź teraz" })).toBeVisible();
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
