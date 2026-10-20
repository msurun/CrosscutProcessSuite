// src/components/Stepper.test.tsx

/**
 * Behaviour tests for {@link Stepper}: order, numbering, state words, unique
 * state markers, the current-step marker and optional detail text.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Stepper } from "./Stepper";
import type { StepInfo, StepState } from "./Stepper";

const STATE_LABELS: Record<StepState, string> = {
  todo: "To do",
  active: "In progress",
  done: "Done",
  blocked: "Blocked",
};

const SAMPLE_STEPS: StepInfo[] = [
  { id: "intake", label: "Intake", state: "done" },
  { id: "review", label: "Review", state: "active" },
  { id: "publish", label: "Publish", state: "todo" },
];

describe("Stepper", () => {
  it("renders one list item per step, in order", () => {
    render(<Stepper steps={SAMPLE_STEPS} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const items = screen.getAllByRole("listitem");

    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Intake");
    expect(items[1]).toHaveTextContent("Review");
    expect(items[2]).toHaveTextContent("Publish");
  });

  it("numbers the steps from one upward", () => {
    render(<Stepper steps={SAMPLE_STEPS} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const numbers = document.querySelectorAll(".stepper-number");

    expect(Array.from(numbers).map((node) => node.textContent)).toEqual(["1", "2", "3"]);
  });

  it("shows the state word from the provided labels", () => {
    render(<Stepper steps={SAMPLE_STEPS} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const words = document.querySelectorAll(".stepper-state");

    expect(Array.from(words).map((node) => node.textContent)).toEqual([
      "Done",
      "In progress",
      "To do",
    ]);
  });

  it("gives each state its own marker character", () => {
    const steps: StepInfo[] = [
      { id: "a", label: "A", state: "todo" },
      { id: "b", label: "B", state: "active" },
      { id: "c", label: "C", state: "done" },
      { id: "d", label: "D", state: "blocked" },
    ];
    render(<Stepper steps={steps} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const markers = Array.from(document.querySelectorAll(".stepper-marker")).map(
      (node) => node.textContent,
    );

    expect(new Set(markers).size).toBe(4);
    expect(markers).toEqual(["\u25CB", "\u25D0", "\u2713", "\u25A0"]);
  });

  it("marks only the active step as current", () => {
    render(<Stepper steps={SAMPLE_STEPS} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const current = screen.getAllByRole("listitem").filter(
      (item) => item.getAttribute("aria-current") === "step",
    );

    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Review");
  });

  it("marks the first blocked step as current when nothing is active", () => {
    const steps: StepInfo[] = [
      { id: "a", label: "A", state: "done" },
      { id: "b", label: "B", state: "blocked" },
      { id: "c", label: "C", state: "blocked" },
    ];
    render(<Stepper steps={steps} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const current = screen.getAllByRole("listitem").filter(
      (item) => item.getAttribute("aria-current") === "step",
    );

    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("B");
  });

  it("exposes the aria-label on the list", () => {
    render(<Stepper steps={SAMPLE_STEPS} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    expect(screen.getByRole("list", { name: "Wizard" })).toBeInTheDocument();
  });

  it("renders the detail only when it is given", () => {
    const steps: StepInfo[] = [
      { id: "a", label: "A", state: "done", detail: "Finished at noon" },
      { id: "b", label: "B", state: "active" },
    ];
    render(<Stepper steps={steps} ariaLabel="Wizard" stateLabels={STATE_LABELS} />);

    const details = document.querySelectorAll(".stepper-detail");

    expect(details).toHaveLength(1);
    expect(details[0]).toHaveTextContent("Finished at noon");
  });
});
