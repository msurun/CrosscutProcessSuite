// Unit tests for useTheme.ts: resolving the light, dark and system preference, saving and
// loading it in localStorage (garbage or blocked storage falls back to system), and applying
// the data-theme attribute to the root element.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyTheme,
  loadPreference,
  resolveTheme,
  savePreference,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemePreference,
} from "./useTheme";

describe("resolveTheme", () => {
  // The resolved theme for every preference, with the system in dark mode
  // and then in light mode.
  const cases: Array<[ThemePreference, boolean, ResolvedTheme]> = [
    ["light", true, "light"],
    ["light", false, "light"],
    ["dark", true, "dark"],
    ["dark", false, "dark"],
    ["system", true, "dark"],
    ["system", false, "light"],
  ];

  it.each(cases)(
    "resolves preference %s with systemPrefersDark=%s to %s",
    (preference, systemPrefersDark, expectedTheme) => {
      expect(resolveTheme(preference, systemPrefersDark)).toBe(expectedTheme);
    },
  );
});

describe("loadPreference", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns system when storage is empty", () => {
    expect(loadPreference()).toBe("system");
  });

  it("returns system when storage holds garbage", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "banana");
    expect(loadPreference()).toBe("system");
  });

  it("returns system when reading storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadPreference()).toBe("system");
  });

  it("round-trips a saved preference", () => {
    savePreference("dark");
    expect(loadPreference()).toBe("dark");
  });
});

describe("applyTheme", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sets the theme data attribute on the root element", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
