// Browser test of the tuning wizard for integrating (level) loops, in Polish at 1440 and 390 px:
// the ramp model and the integrating recommendation on a clean window, the averaging-level input,
// refusals with their reasons (a window without an output move, a first-order process marked
// integrating), axe (serious/critical none) and no horizontal scroll at 390 px.
// Needs the dataset `level_integrating_demo`: python e2e/support/make_level_dataset.py <data root>.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "level_integrating_demo";
const tuningUrl = (loop: string): string => `/#/d/${DATASET}/loops/${loop}/tuning`;

/** Fails when axe finds a serious or critical violation, or the page scrolls sideways at 390 px. */
async function expectAccessibleAndFitting(page: Page, width: number): Promise<void> {
  if (width === 390) {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
  }
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
}

/** Opens the wizard of a loop and waits until the model step is shown. */
async function openTuning(page: Page, loop: string, width: number): Promise<void> {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(tuningUrl(loop));
  await expect(page.getByRole("heading", { name: "2. Sprawdź model" })).toBeVisible({ timeout: 30_000 });
}

/** Applies a window typed in minutes and waits for the page to take it. */
async function applyWindow(page: Page, startMin: string, endMin: string): Promise<void> {
  await page.getByLabel("Początek (min)").fill(startMin);
  await page.getByLabel("Koniec (min)").fill(endMin);
  await page.getByRole("button", { name: "Zastosuj okno" }).click();
}

for (const width of [1440, 390]) {
  test(`integrating loop: model, recommendation, averaging level @${width}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("response", (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
    await openTuning(page, "LIC1", width);
    // The suggested window starts only 5 minutes before the first move: refused with a reason.
    await expect(page.getByText("przed pierwszym ruchem jest mniej niż jedna piąta okna")).toBeVisible();
    await applyWindow(page, "0", "119");
    await expect(page.getByText("Nachylenie rampy")).toBeVisible();
    await expect(page.getByText(/Propozycja \(reguła SIMC dla procesu całkującego\)/)).toBeVisible();
    await expect(page.getByText(/Czas martwy/).first()).toBeVisible();
    await expect(page.getByText(/\(zakres [\d,.]+-[\d,.]+ s\)/).first()).toBeVisible();
    await expect(page.getByText(/z górną granicą zakresu czasu opóźnienia/)).toBeVisible();
    await expect(page.getByRole("note").filter({ hasText: "Strojenie pętli poziomu jest eksperymentalne" })).toBeVisible();
    await expect(page.getByText(/Przy tych nastawach spodziewane jest przeregulowanie/)).toBeVisible();
    await expect(page.getByText("Stała czasowa", { exact: true })).toHaveCount(0);
    await page.getByLabel(/Największe dopuszczalne wahanie/).fill("2");
    await expect(page.getByText("Podaj obie wartości albo zostaw oba pola puste.")).toBeVisible();
    await page.getByLabel(/Spodziewany skok obciążenia/).fill("4");
    await expect(page.getByText(/Przy tym limicie stała czasowa układu zamkniętego wynosi tau_c = /)).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectAccessibleAndFitting(page, width);
    expect(errors).toEqual([]);
  });

  test(`integrating loop: refusals with reasons @${width}`, async ({ page }) => {
    await openTuning(page, "LIC1", width);
    await applyWindow(page, "0", "16");
    await expect(page.getByText("Wyjście regulatora nie ruszyło się w tym oknie.")).toBeVisible();
    await expect(page.getByText(/Wybierz okno, w którym ruszano wyjściem/)).toBeVisible();
    await expect(page.getByText(/Propozycja/)).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    await expectAccessibleAndFitting(page, width);

    await openTuning(page, "LIC2", width);
    await applyWindow(page, "0", "119");
    await expect(page.getByText("Rampa słabo opisuje to okno (R² poniżej 0,8).")).toBeVisible();
    await expect(page.getByText(/ustaw typ procesu na samoregulujący/)).toBeVisible();
    await expect(page.getByText(/model pierwszego rzędu tak/)).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectAccessibleAndFitting(page, width);
  });
}
