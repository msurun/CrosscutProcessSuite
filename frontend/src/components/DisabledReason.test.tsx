// frontend/src/components/DisabledReason.test.tsx
/**
 * Unit tests for DisabledReason component.
 * Verifies aria-disabled attribute, aria-describedby linkage, focusability, and click suppression.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DisabledReason } from "./DisabledReason";

const mockT = (key: string) => key;

describe("DisabledReason", () => {
  it("renders child without disabling attributes when disabled is false", () => {
    const handleClick = vi.fn();
    render(
      <DisabledReason disabled={false} reason="Missing role">
        <button type="button" onClick={handleClick}>Action</button>
      </DisabledReason>
    );

    const button = screen.getByRole("button", { name: "Action" });
    expect(button).not.toHaveAttribute("aria-disabled");
    fireEvent.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("adds aria-disabled, links reason via aria-describedby, and stays focusable", () => {
    const handleClick = vi.fn();
    render(
      <DisabledReason disabled={true} reason="auth.reason.requires_operator" t={mockT}>
        <button type="button" onClick={handleClick}>Action</button>
      </DisabledReason>
    );

    const button = screen.getByRole("button", { name: "Action" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();

    const describedBy = button.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();

    const reasonEl = screen.getByTestId("disabled-reason-text");
    expect(reasonEl).toHaveAttribute("id", describedBy!);
    expect(reasonEl).toHaveTextContent("auth.reason.requires_operator");
  });

  it("suppresses click and keyboard activation when disabled is true", () => {
    const handleClick = vi.fn();
    render(
      <DisabledReason disabled={true} reason="Insufficient authority">
        <button type="button" onClick={handleClick}>Guarded Action</button>
      </DisabledReason>
    );

    const button = screen.getByRole("button", { name: "Guarded Action" });
    fireEvent.click(button);
    expect(handleClick).not.toHaveBeenCalled();

    fireEvent.keyDown(button, { key: "Enter" });
    expect(handleClick).not.toHaveBeenCalled();

    fireEvent.keyDown(button, { key: " " });
    expect(handleClick).not.toHaveBeenCalled();
  });

  it("merges existing aria-describedby on the child element", () => {
    render(
      <DisabledReason disabled={true} reason="Action locked">
        <button type="button" aria-describedby="existing-hint">Trigger</button>
      </DisabledReason>
    );

    const button = screen.getByRole("button", { name: "Trigger" });
    const describedBy = button.getAttribute("aria-describedby");
    expect(describedBy).toContain("existing-hint");
  });

  describe("requiredRole interpolation", () => {
    const labels: Record<string, string> = {
      "auth.reason.requires_role": "Requires role: {role}",
      "auth.role.operator": "Operator",
    };
    const interpolatingT = (key: string, params?: Record<string, string | number>) =>
      (labels[key] ?? key).replace("{role}", String(params?.role ?? "{role}"));

    function renderReason(reason: string, requiredRole?: string) {
      render(
        <DisabledReason disabled={true} reason={reason} t={interpolatingT} requiredRole={requiredRole}>
          <button type="button">Go</button>
        </DisabledReason>
      );
      return screen.getByTestId("disabled-reason-text");
    }

    it("shows the translated role and no literal placeholder", () => {
      const el = renderReason("auth.reason.requires_role", "operator");
      expect(el).toHaveTextContent("Requires role: Operator");
      expect(el.textContent).not.toContain("{role}");
    });

    it("falls back to the raw role id when it has no translation", () => {
      expect(renderReason("auth.reason.requires_role", "auditor")).toHaveTextContent("Requires role: auditor");
    });

    it("never leaves a literal placeholder when requiredRole is absent", () => {
      expect(renderReason("auth.reason.requires_role").textContent).not.toContain("{role}");
    });

    it("passes non-auth reasons through unchanged", () => {
      expect(renderReason("Plain {role} text", "operator")).toHaveTextContent("Plain {role} text");
    });
  });
});
