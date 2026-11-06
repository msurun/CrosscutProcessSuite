// frontend/src/components/ModalDialog.test.tsx
/**
 * Unit tests for the shared ModalDialog: ARIA attributes, Escape handling, focus trap
 * and focus return to the element that opened it.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ModalDialog } from "./ModalDialog";

function Harness({ busy = false, onClose }: { busy?: boolean; onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  const close = () => {
    onClose?.();
    setOpen(false);
  };
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>opener</button>
      {open && (
        <ModalDialog title="My title" onClose={close} busy={busy}>
          <input aria-label="first" />
          <button type="button">last</button>
        </ModalDialog>
      )}
    </div>
  );
}

function openDialog() {
  const opener = screen.getByRole("button", { name: "opener" });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe("ModalDialog", () => {
  it("exposes dialog semantics labelled by its title", () => {
    render(<Harness />);
    openDialog();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy as string)).toHaveTextContent("My title");
  });

  it("moves focus into the dialog and returns it to the opener on close", () => {
    render(<Harness />);
    const opener = openDialog();
    expect(screen.getByLabelText("first")).toHaveFocus();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("does not close on Escape while busy", () => {
    const onClose = vi.fn();
    render(<Harness busy onClose={onClose} />);
    openDialog();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("wraps Tab from the last control to the first and Shift+Tab back", () => {
    render(<Harness />);
    openDialog();
    const last = screen.getByRole("button", { name: "last" });
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(screen.getByLabelText("first")).toHaveFocus();
    fireEvent.keyDown(screen.getByLabelText("first"), { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("pulls focus back into the dialog when Tab is pressed from outside", () => {
    render(<Harness />);
    const opener = openDialog();
    opener.focus();
    fireEvent.keyDown(opener, { key: "Tab" });
    expect(screen.getByLabelText("first")).toHaveFocus();
  });
});
