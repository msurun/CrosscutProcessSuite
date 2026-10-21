// Tests the locale lookup of fuzzy example names: translated for bundled text, unchanged otherwise.
import { describe, expect, it } from "vitest";

import { translate } from "./i18n";
import { systemName, termLabel, variableLabel } from "./fuzzyNames";

const pl = (key: string, params?: Record<string, string | number>) => translate("pl", key, params);
const en = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

describe("fuzzyNames", () => {
  it("translates the bundled example texts", () => {
    expect(variableLabel(pl, { id: "mill_power", label: "Mill power" })).toBe("Moc młyna");
    expect(termLabel(pl, "p80", "on_target")).toBe("zgodne z celem");
    expect(systemName(pl, "mill_feed_supervisor", "Mill feed supervisor (synthetic example)")).toContain("Nadzorca");
  });

  it("keeps user-made or edited text and unknown terms", () => {
    expect(variableLabel(pl, { id: "mill_power", label: "My power" })).toBe("My power");
    expect(variableLabel(pl, { id: "own", label: "Own" })).toBe("Own");
    expect(termLabel(pl, "own", "high")).toBe("high");
    expect(systemName(pl, "own", "Own system")).toBe("Own system");
  });

  it("leaves English untouched", () => {
    expect(termLabel(en, "mill_power", "high")).toBe("high");
    expect(variableLabel(en, { id: "mill_power" })).toBe("Mill power");
  });
});
