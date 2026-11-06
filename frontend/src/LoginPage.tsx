// frontend/src/LoginPage.tsx
// Login view: username/password sign-in, 423 lockout countdown from Retry-After, per-status
// error messages in a focused alert. Password is cleared after every attempt and never logged.

import { useEffect, useRef, useState } from "react";
import type { Dispatch, FormEvent, ReactNode, RefObject, SetStateAction } from "react";
import { ApiError, type LoginPayload } from "./authApi";
import { useAuth } from "./AuthContext";
import type { Translate } from "./findings";

export interface LoginPageProps {
  t: Translate;
  onLoginSuccess?: () => void;
}

interface LoginErrorSummaryProps {
  error: string | null;
  lockoutSeconds: number;
  errorRef: RefObject<HTMLDivElement>;
  t: Translate;
}

function LoginErrorSummary({ error, lockoutSeconds, errorRef, t }: LoginErrorSummaryProps) {
  if (!error && lockoutSeconds <= 0) return null;
  const message = lockoutSeconds > 0
    ? t("auth.login.error423", { seconds: lockoutSeconds })
    : (error ?? "");
  return (
    <div
      ref={errorRef}
      tabIndex={-1}
      role="alert"
      aria-live="assertive"
      className="notice notice-warning"
      data-testid="login-error-summary"
      style={{ marginBottom: 16 }}
    >
      <p>{message}</p>
    </div>
  );
}

interface FormFieldProps {
  id: string;
  name: string;
  label: string;
  type: string;
  autoComplete: string;
  value: string;
  disabled: boolean;
  onChange: (val: string) => void;
}

function FormField({ id, name, label, type, autoComplete, value, disabled, onChange }: FormFieldProps) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label htmlFor={id} style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>
        {label}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        required
        style={{ width: "100%", padding: "8px 10px", boxSizing: "border-box" }}
      />
    </div>
  );
}

function resolveErrorMessage(err: unknown, t: Translate): { text: string; lockout?: number } {
  if (!(err instanceof ApiError)) return { text: t("auth.login.errorNetwork") };
  if (err.status === 401) return { text: t("auth.login.error401") };
  if (err.status === 423) {
    const wait = err.retry_after_s ?? 0;
    return wait > 0 ? { text: "", lockout: wait } : { text: t("auth.login.error423NoTime") };
  }
  if (err.status === 429) return { text: t("auth.login.error429") };
  if (err.status === 503) return { text: t("auth.login.error503") };
  return { text: t("auth.login.errorGeneric", { detail: err.detail }) };
}

function useLockoutCountdown(lockout: number, setLockout: Dispatch<SetStateAction<number>>) {
  useEffect(() => {
    if (lockout <= 0) return;
    const timer = setInterval(() => {
      setLockout((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [lockout, setLockout]);
}

interface LoginFormProps {
  username: string;
  password: string;
  isPending: boolean;
  isSubmitting: boolean;
  onSubmit: (e: FormEvent) => void;
  onUsernameChange: (val: string) => void;
  onPasswordChange: (val: string) => void;
  t: Translate;
}

function LoginSubmitButton({ isPending, isSubmitting, disabled, t }: { isPending: boolean; isSubmitting: boolean; disabled: boolean; t: Translate }) {
  return (
    <button
      type="submit"
      disabled={disabled || isPending}
      data-testid="login-submit"
      style={{ width: "100%", padding: "10px 16px", marginTop: 8 }}
    >
      {isSubmitting ? t("auth.login.submitting") : t("auth.login.submitButton")}
    </button>
  );
}

function LoginForm({
  username,
  password,
  isPending,
  isSubmitting,
  onSubmit,
  onUsernameChange,
  onPasswordChange,
  t,
}: LoginFormProps) {
  return (
    <form onSubmit={onSubmit}>
      <FormField id="username" name="username" label={t("auth.login.usernameLabel")} type="text" autoComplete="username" value={username} disabled={isPending} onChange={onUsernameChange} />
      <FormField id="password" name="password" label={t("auth.login.passwordLabel")} type="password" autoComplete="current-password" value={password} disabled={isPending} onChange={onPasswordChange} />
      <LoginSubmitButton isPending={isPending} isSubmitting={isSubmitting} disabled={!username} t={t} />
    </form>
  );
}

interface LoginAttemptState {
  setError: (s: string | null) => void;
  setLockout: (n: number) => void;
  setIsSubmitting: (v: boolean) => void;
  setFailures: Dispatch<SetStateAction<number>>;
}

async function submitLogin(
  login: (p: LoginPayload) => Promise<unknown>,
  payload: LoginPayload,
  t: Translate,
  state: LoginAttemptState,
): Promise<boolean> {
  state.setIsSubmitting(true);
  state.setError(null);
  try {
    await login(payload);
    return true;
  } catch (err: unknown) {
    const res = resolveErrorMessage(err, t);
    state.setError(res.text || null);
    state.setLockout(res.lockout ?? 0);
    state.setFailures((n) => n + 1);
    return false;
  } finally {
    state.setIsSubmitting(false);
  }
}

function useLoginSubmitHandler(
  login: (p: LoginPayload) => Promise<unknown>,
  onSuccess: (() => void) | undefined,
  t: Translate,
  errorRef: RefObject<HTMLDivElement>
) {
  const [error, setError] = useState<string | null>(null);
  const [lockout, setLockout] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [failures, setFailures] = useState(0);
  useLockoutCountdown(lockout, setLockout);
  useEffect(() => {
    if (failures > 0) errorRef.current?.focus();
  }, [failures, errorRef]);

  const executeSubmit = async (username: string, password: string) => {
    const state = { setError, setLockout, setIsSubmitting, setFailures };
    const ok = await submitLogin(login, { username, password }, t, state);
    if (ok) onSuccess?.();
  };

  return { error, lockout, isSubmitting, executeSubmit };
}

function LoginPageLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="login-page-container" style={{ maxWidth: 400, width: "100%", margin: "40px auto", padding: 24, boxSizing: "border-box" }}>
      <h1 style={{ marginTop: 0, marginBottom: 8 }}>{title}</h1>
      <p style={{ marginTop: 0, marginBottom: 20, color: "var(--color-muted, #666)" }}>{subtitle}</p>
      {children}
    </div>
  );
}

function useLoginPageFormState() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);
  return { username, setUsername, password, setPassword, errorRef };
}

export function LoginPage({ t, onLoginSuccess }: LoginPageProps) {
  const { login } = useAuth();
  const form = useLoginPageFormState();
  const h = useLoginSubmitHandler(login, onLoginSuccess, t, form.errorRef);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (h.isSubmitting || h.lockout > 0) return;
    const pwd = form.password;
    form.setPassword("");
    void h.executeSubmit(form.username, pwd);
  };

  return (
    <LoginPageLayout title={t("auth.login.title")} subtitle={t("auth.login.subtitle")}>
      <LoginErrorSummary error={h.error} lockoutSeconds={h.lockout} errorRef={form.errorRef} t={t} />
      <LoginForm username={form.username} password={form.password} isPending={h.isSubmitting || h.lockout > 0} isSubmitting={h.isSubmitting} onSubmit={handleSubmit} onUsernameChange={form.setUsername} onPasswordChange={form.setPassword} t={t} />
    </LoginPageLayout>
  );
}
