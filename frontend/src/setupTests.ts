// Vitest setup file, run before the test files. It adds the jest-dom matchers (such as
// toBeInTheDocument) to Vitest's expect, so component tests can assert on rendered DOM.
// It also pins <html lang> to English before every test: number formatting follows that
// attribute (and, when it is empty, the machine's locale), so tests must not depend on the
// locale of whoever runs them.
import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

// jsdom has no window.matchMedia, and uPlot reads it when the chart module loads.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
}

beforeEach(() => {
  document.documentElement.lang = "en";
});
