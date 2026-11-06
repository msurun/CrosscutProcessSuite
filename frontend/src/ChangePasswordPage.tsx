// frontend/src/ChangePasswordPage.tsx
/**
 * Change-password view, shown when a password change is forced or requested.
 * Validates on the client, maps API errors to messages, never keeps or logs passwords.
 */

import { useEffect, useRef, useState } from "react";
import type { FormEvent, RefObject } from "react";
import { ApiError, MIN_PASSWORD_LENGTH, changePassword } from "./authApi";
import { useAuth } from "./AuthContext";
import type { Translate } from "./findings";

export interface ChangePasswordPageProps {
  t: Translate;
  onDone?: () => void;
}

interface PasswordFields {
  oldPassword: string;
  newPassword: string;
  confirm: string;
}

const EMPTY_FIELDS: PasswordFields = { oldPassword: "", newPassword: "", confirm: "" };

/** Returns the first client-side validation message, or null when the input is acceptable. */
function validateFields(f: PasswordFields, t: Translate): string | null {
  if (f.newPassword.length < MIN_PASSWORD_LENGTH) {
    return t("auth.password.tooShort", { min: MIN_PASSWORD_LENGTH });
  }
  if (f.newPassword !== f.confirm) return t("auth.password.mismatch");
  if (f.newPassword === f.oldPassword) return t("auth.password.mustDiffer");
  return null;
}

function lockedMessage(err: ApiError, t: Translate): string {
  if (err.retry_after_s === undefined) return t("auth.password.error423NoTime");
  return t("auth.password.error423", { seconds: err.retry_after_s });
}

/** Maps a failed change-password call to a user-facing message. */
function errorMessage(err: unknown, t: Translate): string {
  if (!(err instanceof ApiError)) {
    const detail = err instanceof Error ? err.message : String(err);
    return t("auth.password.errorGeneric", { detail });
  }
  if (err.status === 403) return t("auth.password.wrongOld");
  if (err.status === 422) return t("auth.password.errorServer", { detail: err.detail });
  if (err.status === 423) return lockedMessage(err, t);
  if (err.status === 429) return t("auth.password.error429");
  if (err.status === 401) return t("auth.password.error401");
  return t("auth.password.errorGeneric", { detail: err.detail });
}

interface PasswordFieldProps {
  id: string;
  label: string;
  autoComplete: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}

function PasswordField({ id, label, autoComplete, value, disabled, onChange }: PasswordFieldProps) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label htmlFor={id} style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>
        {label}
      </label>
      <input
        id={id}
        name={id}
        type="password"
        autoComplete={autoComplete}
        value={value}
        disabled={disabled}
        required
        onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%", padding: "8px 10px", boxSizing: "border-box" }}
      />
    </div>
  );
}

function ErrorSummary({ message, errorRef }: { message: string | null; errorRef: RefObject<HTMLDivElement> }) {
  if (!message) return null;
  return (
    <div
      ref={errorRef}
      tabIndex={-1}
      role="alert"
      aria-live="assertive"
      className="notice notice-warning"
      data-testid="change-password-error"
      style={{ marginBottom: 16 }}
    >
      <p>{message}</p>
    </div>
  );
}

interface ChangeState {
  fields: PasswordFields;
  setFields: (f: PasswordFields) => void;
  error: string | null;
  submitting: boolean;
  errorRef: RefObject<HTMLDivElement>;
  submit: (e: FormEvent) => void;
}

function useChangePassword(t: Translate, onDone?: () => void): ChangeState {
  const { refresh } = useAuth();
  const [fields, setFields] = useState<PasswordFields>(EMPTY_FIELDS);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const run = async (f: PasswordFields) => {
    setSubmitting(true);
    try {
      await changePassword({ old_password: f.oldPassword, new_password: f.newPassword });
      await refresh();
      setFields(EMPTY_FIELDS);
      onDone?.();
    } catch (err: unknown) {
      setFields(EMPTY_FIELDS);
      setError(errorMessage(err, t));
    } finally {
      setSubmitting(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const invalid = validateFields(fields, t);
    setError(invalid);
    if (!invalid) void run(fields);
  };
  return { fields, setFields, error, submitting, errorRef, submit };
}

function PasswordForm({ s, t }: { s: ChangeState; t: Translate }) {
  const set = (key: keyof PasswordFields) => (value: string) => s.setFields({ ...s.fields, [key]: value });
  return (
    <form onSubmit={s.submit} noValidate>
      <PasswordField id="old-password" label={t("auth.password.oldLabel")} autoComplete="current-password" value={s.fields.oldPassword} disabled={s.submitting} onChange={set("oldPassword")} />
      <PasswordField id="new-password" label={t("auth.password.newLabel")} autoComplete="new-password" value={s.fields.newPassword} disabled={s.submitting} onChange={set("newPassword")} />
      <PasswordField id="confirm-password" label={t("auth.password.confirmLabel")} autoComplete="new-password" value={s.fields.confirm} disabled={s.submitting} onChange={set("confirm")} />
      <button type="submit" disabled={s.submitting} style={{ width: "100%", padding: "10px 16px", marginTop: 8 }}>
        {t("auth.password.submit")}
      </button>
    </form>
  );
}

/** Forced or voluntary password change form with a sign-out escape hatch. */
export function ChangePasswordPage({ t, onDone }: ChangePasswordPageProps) {
  const { logout } = useAuth();
  const s = useChangePassword(t, onDone);
  return (
    <div style={{ maxWidth: 400, width: "100%", margin: "40px auto", padding: 24, boxSizing: "border-box" }}>
      <h1 style={{ marginTop: 0, marginBottom: 8 }}>{t("auth.password.title")}</h1>
      <p style={{ marginTop: 0, marginBottom: 20 }}>{t("auth.password.requiredNotice")}</p>
      <ErrorSummary message={s.error} errorRef={s.errorRef} />
      <PasswordForm s={s} t={t} />
      <button type="button" onClick={() => void logout()} style={{ marginTop: 12 }}>
        {t("auth.logout")}
      </button>
    </div>
  );
}
