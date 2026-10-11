import { describe, it, expect } from "vitest";
import { translate, formatNumber, detectLanguage, availableLanguages, FALLBACK_LANGUAGE } from "./i18n";
import englishCatalogue from "./locales/en.json";
import polishCatalogue from "./locales/pl.json";
import spanishCatalogue from "./locales/es.json";

/** Extracts the "{placeholder}" names of a string, e.g. "Hi {name}" -> ["name"]. */
function placeholderNames(text: string): string[] {
  const matches = text.match(/\{(\w+)\}/g) ?? [];
  return matches.map((match) => match.slice(1, -1)).sort();
}

describe("availableLanguages", () => {
  it("lists English, Polish and Spanish", () => {
    expect(availableLanguages()).toContain("en");
    expect(availableLanguages()).toContain("pl");
    expect(availableLanguages()).toContain("es");
  });
});

describe("translate", () => {
  it("returns Polish text for a known key", () => {
    expect(translate("pl", "nav.datasets")).not.toBe(translate("en", "nav.datasets"));
  });

  it("returns the key itself when the key is unknown", () => {
    expect(translate("en", "this.key.does.not.exist")).toBe("this.key.does.not.exist");
  });

  it("falls back to English when the language is unknown", () => {
    expect(translate("zz", "nav.datasets")).toBe(translate("en", "nav.datasets"));
  });

  it("replaces a placeholder with its parameter", () => {
    expect(translate("en", "finding.saturated", { percent: 31 })).toContain("31");
  });

  it("leaves the placeholder in place when its parameter is missing", () => {
    expect(translate("en", "finding.saturated", {})).toContain("{percent}");
  });
});

describe("formatNumber", () => {
  it("uses a decimal comma for Polish", () => {
    expect(formatNumber("pl", 1234.5, 1)).toContain(",");
  });

  it("uses a decimal point for English", () => {
    expect(formatNumber("en", 1234.5, 1)).toContain(".");
  });
});

describe("detectLanguage", () => {
  it("picks the first supported language from the requested list", () => {
    expect(detectLanguage(["pl-PL", "en"], ["en", "pl", "es"])).toBe("pl");
  });

  it("falls back when no requested language is supported", () => {
    expect(detectLanguage(["de"], ["en", "pl"])).toBe(FALLBACK_LANGUAGE);
  });
});

describe("catalogue completeness", () => {
  it("defines every English key in Polish and Spanish", () => {
    const englishKeys = Object.keys(englishCatalogue);
    const polishKeys = Object.keys(polishCatalogue);
    const spanishKeys = Object.keys(spanishCatalogue);

    expect(polishKeys).toEqual(expect.arrayContaining(englishKeys));
    expect(spanishKeys).toEqual(expect.arrayContaining(englishKeys));
  });

  it("keeps the same placeholder names as English in every translation", () => {
    const polish: Record<string, string> = polishCatalogue;
    const spanish: Record<string, string> = spanishCatalogue;
    for (const [key, englishText] of Object.entries(englishCatalogue as Record<string, string>)) {
      const expected = placeholderNames(englishText);
      expect(placeholderNames(polish[key])).toEqual(expected);
      expect(placeholderNames(spanish[key])).toEqual(expected);
    }
  });
});
