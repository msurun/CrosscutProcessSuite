// frontend/src/components/ModalDialog.tsx
/**
 * Shared accessible modal: role=dialog, aria-modal, labelled title, focus trap, Escape to close
 * (ignored while busy) and focus restoration to the element that opened it.
 */

import { useEffect, useId, useRef } from "react";
import type { ReactNode, RefObject } from "react";

export interface ModalDialogProps {
  title: string;
  onClose: () => void;
  busy?: boolean;
  testId?: string;
  children: ReactNode;
}

const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

const BACKDROP_STYLE = {
  position: "fixed" as const,
  inset: 0,
  background: "rgba(0,0,0,0.5)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
};

const BOX_STYLE = {
  background: "var(--color-bg, #fff)",
  padding: 20,
  borderRadius: 4,
  width: 360,
  maxWidth: "90%",
};

function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
}

/** Keeps Tab navigation inside the dialog by wrapping at both ends. */
function trapTab(event: KeyboardEvent, dialog: HTMLElement): void {
  const items = focusableIn(dialog);
  if (items.length === 0) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  const outside = !dialog.contains(active);
  if (event.shiftKey && (outside || active === first || active === dialog)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (outside || active === last)) {
    event.preventDefault();
    first.focus();
  }
}

function useDialogKeys(dialogRef: RefObject<HTMLDivElement>, onClose: () => void, busy: boolean): void {
  const latest = useRef({ onClose, busy });
  latest.current = { onClose, busy };
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!latest.current.busy) latest.current.onClose();
      } else if (event.key === "Tab" && dialogRef.current) {
        trapTab(event, dialogRef.current);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [dialogRef]);
}

function useFocusManagement(dialogRef: RefObject<HTMLDivElement>): void {
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    if (dialog) (focusableIn(dialog)[0] ?? dialog).focus();
    return () => {
      if (opener && opener.isConnected) opener.focus();
    };
  }, [dialogRef]);
}

/** Modal dialog with title, focus trap and Escape handling; mount it only while open. */
export function ModalDialog({ title, onClose, busy = false, testId, children }: ModalDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusManagement(dialogRef);
  useDialogKeys(dialogRef, onClose, busy);

  return (
    <div className="modal-backdrop" style={BACKDROP_STYLE}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={busy || undefined}
        tabIndex={-1}
        data-testid={testId}
        style={BOX_STYLE}
      >
        <h3 id={titleId} style={{ marginTop: 0 }}>{title}</h3>
        {children}
      </div>
    </div>
  );
}
