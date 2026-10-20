// Vitest setup file, run before the test files. It adds the jest-dom matchers (such as
// toBeInTheDocument) to Vitest's expect, so component tests can assert on rendered DOM.
// It also pins <html lang> to English before every test: number formatting follows that
// attribute (and, when it is empty, the machine's locale), so tests must not depend on the
// locale of whoever runs them.
import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

beforeEach(() => {
  document.documentElement.lang = "en";
});
