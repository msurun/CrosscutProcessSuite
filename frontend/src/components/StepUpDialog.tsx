// frontend/src/components/StepUpDialog.tsx
/**
 * Accessible modal dialog prompting for password confirmation (step-up authentication).
 * Traps focus, cancels on Escape when idle, maps API errors to inline text, never keeps the password.
 */

import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, RefObject } from "react";
import { ApiError, stepUp } from "../authApi";
import type { Translate } from "../findings";

export interface StepUpDialogProps {
  isOpen: boolean;
  onSuccess: () => void;
  onCancel: () => void;
  t: Translate;
}

function trapFocus(event: KeyboardEvent<HTMLDivElement>, dialogRef: RefObject<HTMLDivElement>): void {
  if (event.key !== "Tab" || !dialogRef.current) return;
  const elements = dialogRef.current.querySelectorAll<HTMLElement>(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  if (elements.length === 0) return;
  const first = elements[0];
  const last = elements[elements.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function StepUpErrorAlert({ error }: { error: string }) {
  if (!error) return null;
  return (
    <div className="notice notice-warning" role="alert" aria-live="assertive" data-testid="stepup-error">
      <p>{error}</p>
    </div>
  );
}

interface StepUpPasswordInputProps {
  password: string;
  isSubmitting: boolean;
  onPasswordChange: (val: string) => void;
  inputRef: RefObject<HTMLInputElement>;
  label: string;
}

function StepUpPasswordInput({ password, isSubmitting, onPasswordChange, inputRef, label }: StepUpPasswordInputProps) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label htmlFor="stepup-password" style={{ display: "block", marginBottom: 4 }}>
        {label}
      </label>
      <input
        ref={inputRef}
        type="password"
        id="stepup-password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => onPasswordChange(e.target.value)}
        readOnly={isSubmitting}
        style={{ width: "100%", padding: 8, boxSizing: "border-box" }}
        required
      />
    </div>
  );
}

interface StepUpActionButtonsProps {
  isSubmitting: boolean;
  canSubmit: boolean;
  onCancel: () => void;
  confirmLabel: string;
  cancelLabel: string;
}

function StepUpActionButtons({
  isSubmitting,
  canSubmit,
  onCancel,
  confirmLabel,
  cancelLabel,
}: StepUpActionButtonsProps) {
  return (
    <div className="toolbar" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
      <button type="button" onClick={onCancel} disabled={isSubmitting}>
        {cancelLabel}
      </button>
      <button type="submit" disabled={isSubmitting || !canSubmit} data-testid="stepup-submit">
        {confirmLabel}
      </button>
    </div>
  );
}

/** Maps a failed step-up call to the translated message shown inline. */
function resolveStepUpError(err: unknown, t: Translate): string {
  if (!(err instanceof ApiError)) {
    return t("auth.stepup.errorGeneric", { detail: err instanceof Error ? err.message : "" });
  }
  switch (err.status) {
    case 401:
      return t("auth.stepup.error401");
    case 403:
      return t("auth.stepup.errorWrongPassword");
    case 423:
      return err.retry_after_s === undefined
        ? t("auth.stepup.error423NoTime")
        : t("auth.stepup.error423", { seconds: err.retry_after_s });
    case 429:
      return t("auth.stepup.error429");
    default:
      return t("auth.stepup.errorGeneric", { detail: err.detail });
  }
}

/** Remembers the focused element on mount, focuses the input, restores focus on unmount. */
function useStepUpFocus(inputRef: RefObject<HTMLInputElement>) {
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => previous?.focus();
  }, [inputRef]);
}

const BACKDROP_STYLE = {
  position: "fixed" as const,
  inset: 0,
  backgroundColor: "rgba(0,0,0,0.5)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
};

const MODAL_STYLE = {
  background: "var(--color-bg, #fff)",
  color: "var(--color-text, #000)",
  padding: 24,
  borderRadius: 4,
  maxWidth: 420,
  width: "90%",
  boxSizing: "border-box" as const,
};

interface StepUpCallbacks {
  onSuccess: () => void;
  onCancel: () => void;
  t: Translate;
}

/** Owns password/error/pending state; the password is cleared the moment it is submitted. */
function useStepUpSubmit({ onSuccess, onCancel, t }: StepUpCallbacks) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = async (pwd: string) => {
    try {
      await stepUp({ password: pwd });
      if (mounted.current) onSuccess();
    } catch (err: unknown) {
      if (!mounted.current) return;
      setError(resolveStepUpError(err, t));
      if (err instanceof ApiError && err.status === 401) onCancel();
    } finally {
      if (mounted.current) setIsSubmitting(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (isSubmitting || !password) return;
    const pwd = password;
    setPassword("");
    setError("");
    setIsSubmitting(true);
    void run(pwd);
  };

  return { password, setPassword, error, isSubmitting, handleSubmit };
}

interface StepUpModalContentProps {
  dialogRef: RefObject<HTMLDivElement>;
  inputRef: RefObject<HTMLInputElement>;
  error: string;
  password: string;
  isSubmitting: boolean;
  onPasswordChange: (v: string) => void;
  onCancel: () => void;
  onSubmit: (e: FormEvent) => void;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
  t: Translate;
}

function StepUpModalContent(props: StepUpModalContentProps) {
  return (
    <div ref={props.dialogRef} role="dialog" aria-modal="true" aria-labelledby="step-up-title" aria-describedby="step-up-desc" onKeyDown={props.onKeyDown} data-testid="stepup-dialog" style={MODAL_STYLE}>
      <h2 id="step-up-title" style={{ marginTop: 0, marginBottom: 8 }}>{props.t("auth.stepup.title")}</h2>
      <p id="step-up-desc" style={{ marginTop: 0, marginBottom: 16 }}>{props.t("auth.stepup.description")}</p>
      <StepUpErrorAlert error={props.error} />
      <form onSubmit={props.onSubmit}>
        <StepUpPasswordInput password={props.password} isSubmitting={props.isSubmitting} onPasswordChange={props.onPasswordChange} inputRef={props.inputRef} label={props.t("auth.stepup.passwordLabel")} />
        <StepUpActionButtons isSubmitting={props.isSubmitting} canSubmit={Boolean(props.password)} onCancel={props.onCancel} confirmLabel={props.t("auth.stepup.confirmButton")} cancelLabel={props.t("auth.stepup.cancelButton")} />
      </form>
    </div>
  );
}

/** Mounted only while open, so every opening starts with empty password and no error. */
function StepUpDialogBody({ onSuccess, onCancel, t }: StepUpCallbacks) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const h = useStepUpSubmit({ onSuccess, onCancel, t });
  useStepUpFocus(inputRef);

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      if (!h.isSubmitting) onCancel();
    } else {
      trapFocus(e, dialogRef);
    }
  };

  return (
    <div className="modal-backdrop" style={BACKDROP_STYLE}>
      <StepUpModalContent
        dialogRef={dialogRef}
        inputRef={inputRef}
        error={h.error}
        password={h.password}
        isSubmitting={h.isSubmitting}
        onPasswordChange={h.setPassword}
        onCancel={onCancel}
        onSubmit={h.handleSubmit}
        onKeyDown={handleKeyDown}
        t={t}
      />
    </div>
  );
}

export function StepUpDialog({ isOpen, onSuccess, onCancel, t }: StepUpDialogProps) {
  if (!isOpen) return null;
  return <StepUpDialogBody onSuccess={onSuccess} onCancel={onCancel} t={t} />;
}
