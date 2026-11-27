// Browser test of the catalogue Versions section (#165): a draft edit is published as an immutable
// version with a note, a pending publish (seeded as another engineer's request) is approved in the
// approval entry, and the view has no axe violations at 1440 and 390 px and no horizontal scroll.
// Auth is off in this suite, so the "second engineer" request is written to disk by the spec.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const PAGE_URL = `/#/d/${DATASET}/catalogue`;
const SITE = { schema_version: 1, site: { name: "Versions Site", timezone: "UTC" }, sources: [], tags: [] };

function siteDir(): string {
  const root = process.env.E2E_DATA_ROOT;
  if (!root) throw new Error("Set E2E_DATA_ROOT to the data root served by the API under test.");
  return join(root, "_site");
}

/** sha256 of the canonical JSON the API uses (sorted keys, no whitespace; ASCII content only here). */
function canonicalSha(value: unknown): string {
  const sort = (v: unknown): unknown =>
    Array.isArray(v)
      ? v.map(sort)
      : v && typeof v === "object"
        ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort((v as Record<string, unknown>)[k])]))
        : v;
  return createHash("sha256").update(JSON.stringify(sort(value))).digest("hex");
}

function reset(draft?: unknown, pending?: unknown): void {
  rmSync(siteDir(), { recursive: true, force: true });
  mkdirSync(siteDir(), { recursive: true });
  writeFileSync(join(siteDir(), "site.json"), JSON.stringify(SITE, null, 2), "utf-8");
  if (draft) {
    writeFileSync(join(siteDir(), "draft.json"), JSON.stringify(draft), "utf-8");
    writeFileSync(join(siteDir(), "draft.meta.json"), JSON.stringify({ base_sha256: canonicalSha(SITE) }), "utf-8");
  }
  if (pending) writeFileSync(join(siteDir(), "pending_publish.json"), JSON.stringify(pending), "utf-8");
}

const renamed = { ...SITE, site: { name: "Renamed Site", timezone: "UTC" } };

test.afterAll(() => rmSync(siteDir(), { recursive: true, force: true }));

async function openVersions(page: Page): Promise<void> {
  await page.goto(PAGE_URL);
  await page.getByTestId("mode-versions").click();
  await expect(page.getByTestId("site-versions")).toBeVisible({ timeout: 30_000 });
}

test("a draft shows its diff and is published as version 1 with a note", async ({ page }) => {
  reset(renamed);
  await openVersions(page);
  await expect(page.getByTestId("draft-badge")).toHaveText(/Draft|Wersja robocza|Borrador/);
  await expect(page.getByTestId("site-diff")).toContainText("Renamed Site");
  await page.getByLabel(/Note for this version|Notatka do tej wersji|Nota para esta versión/).fill("rename site");
  await page.getByRole("button", { name: /^(Publish|Opublikuj|Publicar)$/ }).click();
  await expect(page.getByTestId("draft-badge")).toHaveText(/No draft|Brak wersji roboczej|Sin borrador/);
  await expect(page.getByText(/rename site/)).toBeVisible();
  expect(JSON.parse(readFileSync(join(siteDir(), "site.json"), "utf-8")).site.name).toBe("Renamed Site");
});

test("a pending publish of another engineer is approved from the approval entry", async ({ page }) => {
  reset(renamed, {
    id: "abc123",
    requested_by: "other-engineer",
    requested_at: "2026-11-26T10:00:00+00:00",
    note: "touches a running loop",
    reasons: ["loop:L1"],
    base_sha256: canonicalSha(SITE), document_sha256: canonicalSha(renamed),
    document: renamed,
  });
  await openVersions(page);
  const entry = page.getByTestId("pending-publish");
  await expect(entry).toContainText("other-engineer");
  await expect(entry).toContainText("loop:L1");
  await entry.getByRole("button", { name: /Approve and publish|Zatwierdź i opublikuj|Aprobar y publicar/ }).click();
  await expect(page.getByTestId("pending-publish")).toHaveCount(0);
  await expect(page.getByText(/other-engineer/).first()).toBeVisible();
  expect(JSON.parse(readFileSync(join(siteDir(), "site.json"), "utf-8")).site.name).toBe("Renamed Site");
});

for (const width of [1440, 390]) {
  test(`versions view has no axe violations and no horizontal scroll @${width}`, async ({ page }) => {
    reset(renamed, {
      id: "abc123", requested_by: "other-engineer", requested_at: "2026-11-26T10:00:00+00:00",
      note: "n", reasons: ["loop:L1"], base_sha256: canonicalSha(SITE), document_sha256: canonicalSha(renamed), document: renamed,
    });
    await page.setViewportSize({ width, height: 900 });
    await openVersions(page);
    await expect(page.getByTestId("pending-publish")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
}
