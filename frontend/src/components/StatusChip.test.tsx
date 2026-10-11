// src/components/StatusChip.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusChip } from "./StatusChip";

/** Icon shown next to the label, keyed by status level. */
const ICON_BY_LEVEL = {
  ok: "●",
  warning: "▲",
  problem: "■",
  unused: "○",
} as const;

type StatusLevel = keyof typeof ICON_BY_LEVEL;

const ALL_LEVELS: StatusLevel[] = ["ok", "warning", "problem", "unused"];

/** Returns the text of the decorative icon for the rendered chip. */
function readIconText(container: HTMLElement): string {
  const icon = container.querySelector('[aria-hidden="true"]');
  if (icon === null) {
    throw new Error("StatusChip did not render an aria-hidden icon element.");
  }
  return icon.textContent ?? "";
}

describe("StatusChip", () => {
  it("shows the label text", () => {
    render(<StatusChip level="ok" label="All systems go" />);

    expect(screen.getByRole("status")).toHaveTextContent("All systems go");
  });

  it.each(ALL_LEVELS)("has the modifier class for the %s level", (level) => {
    render(<StatusChip level={level} label="Pipeline" />);

    expect(screen.getByRole("status")).toHaveClass(`status-chip--${level}`);
  });

  it("uses a different icon per level", () => {
    const iconTexts = ALL_LEVELS.map((level) => {
      const { container, unmount } = render(<StatusChip level={level} label="Pipeline" />);
      const iconText = readIconText(container);
      unmount();
      return iconText;
    });

    expect(new Set(iconTexts).size).toBe(ALL_LEVELS.length);
  });
});
