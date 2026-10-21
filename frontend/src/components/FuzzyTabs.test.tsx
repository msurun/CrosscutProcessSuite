// Tests of the Fuzzy Studio tab strip: click selection, arrow-key navigation and ARIA state.
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { FuzzyTabList, nextTabIndex, type FuzzyTab } from "./FuzzyTabs";

const t = (key: string) => key;

/** Hosts the strip with its own state, like FuzzyPage does. */
function Host() {
  const [tab, setTab] = useState<FuzzyTab>("variables");
  return <FuzzyTabList active={tab} onChange={setTab} t={t} />;
}

describe("FuzzyTabList", () => {
  it("exposes a tablist with four tabs and one selected", () => {
    render(<Host />);
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    expect(screen.getByRole("tab", { name: "fuzzy.tab.variables" })).toHaveAttribute("aria-selected", "true");
  });

  it("switches tab on click", () => {
    render(<Host />);
    fireEvent.click(screen.getByRole("tab", { name: "fuzzy.tab.backtest" }));
    expect(screen.getByRole("tab", { name: "fuzzy.tab.backtest" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "fuzzy.tab.variables" })).toHaveAttribute("aria-selected", "false");
  });

  it("moves with arrow keys, wraps around and supports Home/End", () => {
    render(<Host />);
    const first = screen.getByRole("tab", { name: "fuzzy.tab.variables" });
    fireEvent.keyDown(first, { key: "ArrowRight" });
    const rules = screen.getByRole("tab", { name: "fuzzy.tab.rules" });
    expect(rules).toHaveAttribute("aria-selected", "true");
    expect(rules).toHaveFocus();
    fireEvent.keyDown(rules, { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("tab", { name: "fuzzy.tab.variables" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "fuzzy.tab.backtest" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "fuzzy.tab.backtest" }), { key: "Home" });
    expect(screen.getByRole("tab", { name: "fuzzy.tab.variables" })).toHaveAttribute("aria-selected", "true");
  });

  it("ignores other keys", () => {
    expect(nextTabIndex("a", 1, 4)).toBeNull();
    expect(nextTabIndex("End", 0, 4)).toBe(3);
  });
});
