// frontend/src/AuthGate.tsx
// Decides what the user sees before the app: the session check, the login, the first-run hint
// (users file missing), the forced password change. With auth off the app is shown at once.

import type { ReactNode } from "react";
import { useAuth } from "./AuthContext";
import { ChangePasswordPage } from "./ChangePasswordPage";
import type { Translate } from "./findings";
import { LoginPage } from "./LoginPage";

export interface AuthGateProps {
  t: Translate;
  children: ReactNode;
}

function UninitialisedNotice({ t }: { t: Translate }) {
  return (
    <main className="notice notice-warning" role="alert" data-testid="auth-uninitialised" style={{ maxWidth: 560, margin: "40px auto", padding: 24 }}>
      <h1>{t("auth.uninitialised.title")}</h1>
      <p>{t("auth.uninitialised.text")}</p>
    </main>
  );
}

/** Renders `children` only for a usable session (or when authentication is off). */
export function AuthGate({ t, children }: AuthGateProps) {
  const { status, mustChangePassword, refresh } = useAuth();
  if (status === "loading") {
    return <p role="status" data-testid="auth-loading" style={{ padding: 24 }}>{t("auth.loading")}</p>;
  }
  if (status === "uninitialised") return <UninitialisedNotice t={t} />;
  if (status === "anonymous") return <LoginPage t={t} />;
  if (status === "authenticated" && mustChangePassword) {
    return <ChangePasswordPage t={t} onDone={() => void refresh()} />;
  }
  return <>{children}</>;
}
