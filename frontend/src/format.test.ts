// Behavioural tests for the formatting helpers: locale separators, significant
// digits, sign rules and the language-independent DCS format.
import { afterEach, describe, expect, it } from "vitest";

import {
  formatDcs,
  formatFixed,
  formatPercent,
  formatSignificant,
  formatSigned,
} from "./format";

function setLanguage(lang: string): void {
  document.documentElement.lang = lang;
}

afterEach(() => {
  setLanguage("");
});

describe("formatSignificant", () => {
  it("keeps a whole number without grouping", () => {
    setLanguage("en");
    expect(formatSignificant(2600)).toBe("2600");
  });

  it("uses a dot decimal in en", () => {
    setLanguage("en");
    expect(formatSignificant(0.064511)).toBe("0.06451");
  });

  it("uses a comma decimal in pl", () => {
    setLanguage("pl");
    expect(formatSignificant(0.064511)).toBe("0,06451");
  });

  it("rounds 15.1729 to four significant digits in pl", () => {
    setLanguage("pl");
    expect(formatSignificant(15.1729)).toBe("15,17");
  });

  it("rounds 12345.6 to 12350 without a thousands separator", () => {
    setLanguage("en");
    expect(formatSignificant(12345.6)).toBe("12350");
  });

  it("renders NaN as an en dash", () => {
    setLanguage("en");
    expect(formatSignificant(Number.NaN)).toBe("–");
  });

  it("renders Infinity as an en dash", () => {
    setLanguage("en");
    expect(formatSignificant(Number.POSITIVE_INFINITY)).toBe("–");
  });
});

describe("formatFixed", () => {
  it("rounds to the requested decimals with a dot in en", () => {
    setLanguage("en");
    expect(formatFixed(3.14159, 2)).toBe("3.14");
  });

  it("uses a comma decimal in pl", () => {
    setLanguage("pl");
    expect(formatFixed(3.14159, 2)).toBe("3,14");
  });

  it("drops the minus sign from a value that rounds to zero", () => {
    setLanguage("en");
    expect(formatFixed(-0.04, 1)).toBe("0.0");
  });

  it("renders NaN as an en dash", () => {
    setLanguage("en");
    expect(formatFixed(Number.NaN, 2)).toBe("–");
  });

  it("renders Infinity as an en dash", () => {
    setLanguage("en");
    expect(formatFixed(Number.NEGATIVE_INFINITY, 2)).toBe("–");
  });
});

describe("formatSigned", () => {
  it("adds a plus sign to a positive value", () => {
    setLanguage("en");
    expect(formatSigned(12.5, 1)).toBe("+12.5");
  });

  it("keeps a minus sign on a negative value", () => {
    setLanguage("en");
    expect(formatSigned(-3.0, 1)).toBe("-3.0");
  });

  it("shows zero without any sign", () => {
    setLanguage("en");
    expect(formatSigned(0.0, 1)).toBe("0.0");
  });
});

describe("formatDcs", () => {
  it("keeps a dot decimal while the language is pl", () => {
    setLanguage("pl");
    expect(formatDcs(0.064511)).toBe("0.06451");
  });

  it("rounds to four significant digits", () => {
    setLanguage("en");
    expect(formatDcs(15.1729)).toBe("15.17");
  });

  it("renders NaN as an en dash", () => {
    setLanguage("en");
    expect(formatDcs(Number.NaN)).toBe("–");
  });
});

describe("formatPercent", () => {
  it("appends a space and a percent sign with zero decimals", () => {
    setLanguage("en");
    expect(formatPercent(12.4)).toBe("12 %");
  });

  it("honours the requested decimals in pl", () => {
    setLanguage("pl");
    expect(formatPercent(12.34, 1)).toBe("12,3 %");
  });
});
