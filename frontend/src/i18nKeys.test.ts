// Guards the catalogues against missing keys: every static key passed to t("...") in the source
// must exist in en.json, otherwise the UI would show the raw key to the user.
import { describe, expect, it } from "vitest";

import en from "./locales/en.json";

/** The text of every source file except tests, keyed by path (Vite reads them at build time). */
const sources = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.*", "!./setupTests.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Keys written as string literals in calls like t("a.b") or t("a.b", {...}). */
function staticKeys(source: string): string[] {
  return [...source.matchAll(/\bt\(\s*"([A-Za-z][\w.]*)"/g)].map((match) => match[1]);
}

describe("locale keys", () => {
  it("scans a meaningful number of source files", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it('every static t("key") used in the source exists in en.json', () => {
    const catalogue = en as Record<string, string>;
    const missing: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      for (const key of staticKeys(source)) {
        if (!(key in catalogue)) missing.push(`${key}  (${file})`);
      }
    }
    expect(missing).toEqual([]);
  });
});
