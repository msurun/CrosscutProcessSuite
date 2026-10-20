// src/components/ValveChecklist.test.tsx
// Behaviour tests for ValveChecklist: the continue gate and the callbacks.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ValveChecklist } from "./ValveChecklist";

/** Fake translator: the key plus stringified params. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** Renders the checklist with the given ticks and returns the spies. */
function setup(checks: [boolean, boolean, boolean]) {
  const onToggle = vi.fn();
  const onContinue = vi.fn();
  const onBack = vi.fn();
  render(
    <ValveChecklist checks={checks} onToggle={onToggle} onContinue={onContinue} onBack={onBack} t={t} />,
  );
  return { onToggle, onContinue, onBack };
}

describe("ValveChecklist", () => {
  it("shows the title and three checkboxes in order", () => {
    setup([false, false, false]);

    expect(screen.getByRole("heading", { name: "valve.checklist.title" })).toBeInTheDocument();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(3);
    expect(screen.getByLabelText("valve.check.operator")).toBe(boxes[0]);
    expect(screen.getByLabelText("valve.check.manual")).toBe(boxes[1]);
    expect(screen.getByLabelText("valve.check.abort")).toBe(boxes[2]);
  });

  it("reflects the ticked state", () => {
    setup([true, false, true]);

    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.map((box) => (box as HTMLInputElement).checked)).toEqual([true, false, true]);
  });

  it.each([
    [[false, false, false]],
    [[true, true, false]],
    [[false, true, true]],
  ] as [[boolean, boolean, boolean]][])("disables continue while not all are ticked (%j)", (checks) => {
    const { onContinue } = setup(checks);

    const button = screen.getByRole("button", { name: "valve.checklist.continue" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("enables continue when all three are ticked and calls back", () => {
    const { onContinue } = setup([true, true, true]);

    const button = screen.getByRole("button", { name: "valve.checklist.continue" });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  it("reports the index of the toggled box", () => {
    const { onToggle } = setup([false, false, false]);

    fireEvent.click(screen.getByLabelText("valve.check.manual"));

    expect(onToggle).toHaveBeenCalledWith(1);
  });

  it("calls onBack even when the gate is closed", () => {
    const { onBack } = setup([false, false, false]);

    fireEvent.click(screen.getByRole("button", { name: "valve.checklist.back" }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
