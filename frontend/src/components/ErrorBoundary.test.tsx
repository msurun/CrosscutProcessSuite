// Behaviour tests for ErrorBoundary: children pass through untouched, render errors
// become a translated alert, and both the reload button and a resetKey change recover.
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";
import type { Translate } from "../findings";

const t: Translate = (key, params) => key + (params ? JSON.stringify(params) : "");

type ChildProps = { shouldThrow: boolean };

/** Child that throws during render when `shouldThrow` is true. */
function ThrowingChild({ shouldThrow }: ChildProps): React.ReactNode {
  if (shouldThrow) {
    throw new Error("boom");
  }
  return <p>child content</p>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs every caught error; silence it so the test output stays readable.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it("renders the children when nothing throws", () => {
    render(
      <ErrorBoundary t={t}>
        <ThrowingChild shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByText("child content")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the alert with the error message when a child throws", () => {
    render(
      <ErrorBoundary t={t}>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("error.boundary")).toBeTruthy();
    expect(screen.getByText('error.boundaryDetail{"reason":"boom"}')).toBeTruthy();
  });

  it("re-renders the children once the child stops throwing", () => {
    const shouldThrow = { current: true };
    function Child() {
      return <ThrowingChild shouldThrow={shouldThrow.current} />;
    }
    render(
      <ErrorBoundary t={t}>
        <Child />
      </ErrorBoundary>,
    );
    shouldThrow.current = false;

    fireEvent.click(screen.getByText("error.reload"));

    expect(screen.getByText("child content")).toBeTruthy();
  });

  it("recovers when resetKey changes after an error", () => {
    const shouldThrow = { current: true };
    function Child() {
      return <ThrowingChild shouldThrow={shouldThrow.current} />;
    }
    const { rerender } = render(
      <ErrorBoundary t={t} resetKey="first-screen">
        <Child />
      </ErrorBoundary>,
    );
    shouldThrow.current = false;

    rerender(
      <ErrorBoundary t={t} resetKey="second-screen">
        <Child />
      </ErrorBoundary>,
    );

    expect(screen.getByText("child content")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders the error message as text, not as HTML", () => {
    function HtmlChild(): React.ReactNode {
      throw new Error("<b>x</b>");
    }
    render(
      <ErrorBoundary t={t}>
        <HtmlChild />
      </ErrorBoundary>,
    );

    expect(screen.getByText('error.boundaryDetail{"reason":"<b>x</b>"}')).toBeTruthy();
    expect(screen.queryByText("x")).toBeNull();
  });
});
