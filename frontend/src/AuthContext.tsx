// frontend/src/AuthContext.tsx
/**
 * React Authentication context and hooks (useAuth, useCan).
 * Provides user state, permissions, login/logout actions, and step-up coordination.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  fetchAuthConfig,
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  setStepUpHandler,
  subscribePasswordChangeRequired,
  subscribeUnauthorized,
  type AuthSession,
  type AuthUser,
  type LoginPayload,
} from "./authApi";
import { StepUpDialog } from "./components/StepUpDialog";
import type { Translate } from "./findings";

export const DEFAULT_ROLE_PERMISSIONS: Readonly<Record<string, readonly string[]>> = {
  viewer: [
    "audit.view",
    "data.view",
    "gw.kill",
    "gw.mode.down",
    "gw.reject",
    "gw.view",
  ],
  operator: [
    "analysis.run",
    "audit.view",
    "data.view",
    "gw.approve",
    "gw.kill",
    "gw.mode.down",
    "gw.re_enable.hold_off",
    "gw.reject",
    "gw.view",
    "job.stop",
  ],
  engineer: [
    "analysis.run",
    "audit.view",
    "config.edit",
    "connector.use",
    "data.import",
    "data.view",
    "gw.approve",
    "gw.kill",
    "gw.mode.down",
    "gw.mode.up.advisory",
    "gw.mode.up.confirm",
    "gw.mode.up.dry_run",
    "gw.propose",
    "gw.re_enable.hold_off",
    "gw.re_enable.stopped",
    "gw.reject",
    "gw.view",
    "job.manage",
    "job.stop",
    "policy.edit",
  ],
  lead: [
    "analysis.run",
    "audit.view",
    "config.edit",
    "connector.use",
    "data.import",
    "data.view",
    "gw.approve",
    "gw.kill",
    "gw.kill.reset",
    "gw.mode.down",
    "gw.mode.up.advisory",
    "gw.mode.up.confirm",
    "gw.mode.up.dry_run",
    "gw.mode.up.supervised",
    "gw.propose",
    "gw.re_enable.hold_off",
    "gw.re_enable.stopped",
    "gw.reject",
    "gw.view",
    "job.manage",
    "job.stop",
    "policy.edit",
    "policy.pin",
    "policy.reload",
  ],
  admin: [
    "audit.view",
    "data.view",
    "gw.kill",
    "gw.mode.down",
    "gw.reject",
    "gw.view",
    "users.manage",
  ],
  service: [
    "gw.propose",
  ],
};

/** Roles ordered from least to most privileged (the service principal is not a login role). */
export const ROLE_ORDER: readonly string[] = ["viewer", "operator", "engineer", "lead", "admin"];

function computeLowestRoles(): Readonly<Record<string, string>> {
  const lowest: Record<string, string> = {};
  for (const role of ROLE_ORDER) {
    for (const permission of DEFAULT_ROLE_PERMISSIONS[role] ?? []) {
      if (!(permission in lowest)) lowest[permission] = role;
    }
  }
  return lowest;
}

export const PERMISSION_LOWEST_ROLE: Readonly<Record<string, string>> = computeLowestRoles();

const KNOWN_PERMISSIONS: ReadonlySet<string> = new Set(
  Object.values(DEFAULT_ROLE_PERMISSIONS).flat(),
);
/** "disabled" means the API runs with auth off (dev / e2e): no login, every control enabled. */
export type AuthStatus = "loading" | "anonymous" | "authenticated" | "uninitialised" | "disabled";

export interface CanResult {
  allowed: boolean;
  reason: string;
  requiredRole?: string;
}

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  roles: string[];
  permissions: string[];
  csrf: string | null;
  mustChangePassword: boolean;
  login: (payload: LoginPayload) => Promise<AuthSession>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  requestStepUp: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export interface AuthProviderProps {
  children: ReactNode;
  t?: Translate;
}

const defaultTranslate: Translate = (key) => key;

interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  roles: string[];
  permissions: string[];
  csrf: string | null;
  mustChangePassword: boolean;
}

const INITIAL_STATE: AuthState = {
  status: "loading",
  user: null,
  roles: [],
  permissions: [],
  csrf: null,
  mustChangePassword: false,
};

function useAuthStateManager() {
  const [state, setState] = useState<AuthState>(INITIAL_STATE);
  const mountedRef = useRef(true);

  const applySession = useCallback((s: AuthSession) => {
    if (!mountedRef.current) return;
    setState({
      status: "authenticated",
      user: s.user,
      roles: s.roles,
      permissions: s.permissions,
      csrf: s.csrf,
      mustChangePassword: s.must_change_password,
    });
  }, []);

  const markPasswordChangeRequired = useCallback(() => {
    if (!mountedRef.current) return;
    setState((prev) => ({ ...prev, mustChangePassword: true }));
  }, []);

  const clearSession = useCallback((status: AuthStatus = "anonymous") => {
    if (!mountedRef.current) return;
    setState({ ...INITIAL_STATE, status });
  }, []);

  return { ...state, applySession, clearSession, markPasswordChangeRequired, mountedRef };
}

function useStepUpManager() {
  const [isStepUpOpen, setIsStepUpOpen] = useState(false);
  const waitersRef = useRef<Array<(result: boolean) => void>>([]);

  const requestStepUp = useCallback((): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      waitersRef.current.push(resolve);
      setIsStepUpOpen(true);
    });
  }, []);

  const resolveStepUp = useCallback((success: boolean) => {
    const waiters = waitersRef.current;
    waitersRef.current = [];
    setIsStepUpOpen(false);
    for (const waiter of waiters) {
      waiter(success);
    }
  }, []);

  return { isStepUpOpen, requestStepUp, resolveStepUp };
}

/** Reads the public config: "disabled" / "uninitialised" settle the status, null means ask /auth/me. */
async function statusFromConfig(): Promise<AuthStatus | null> {
  try {
    const config = await fetchAuthConfig();
    if (!config.auth_enabled) return "disabled";
    return config.initialised ? null : "uninitialised";
  } catch {
    return null;
  }
}

function useRefreshAction(apply: (s: AuthSession) => void, clear: (st?: AuthStatus) => void) {
  return useCallback(async () => {
    const settled = await statusFromConfig();
    if (settled !== null) {
      clear(settled);
      return;
    }
    try {
      apply(await fetchMe());
    } catch (err: unknown) {
      const is503 = err instanceof ApiError && err.status === 503;
      clear(is503 ? "uninitialised" : "anonymous");
    }
  }, [apply, clear]);
}

function useAuthActions(apply: (s: AuthSession) => void, clear: (st?: AuthStatus) => void) {
  const refresh = useRefreshAction(apply, clear);

  const login = useCallback(async (payload: LoginPayload): Promise<AuthSession> => {
    const session = await apiLogin(payload);
    apply(session);
    return session;
  }, [apply]);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await apiLogout();
    } catch {
      // Clear session even if network logout fails
    } finally {
      clear("anonymous");
    }
  }, [clear]);

  return { refresh, login, logout };
}

function useAuthLifecycle(
  requestStepUp: () => Promise<boolean>,
  handlers: { clearSession: () => void; markPasswordChangeRequired: () => void },
  refresh: () => Promise<void>,
  mountedRef: { current: boolean }
) {
  const { clearSession, markPasswordChangeRequired } = handlers;
  useEffect(() => {
    mountedRef.current = true;
    setStepUpHandler(requestStepUp);
    const offUnauthorized = subscribeUnauthorized(clearSession);
    const offPasswordChange = subscribePasswordChangeRequired(markPasswordChangeRequired);
    void refresh();
    return () => {
      mountedRef.current = false;
      setStepUpHandler(null);
      offUnauthorized();
      offPasswordChange();
    };
  }, [clearSession, markPasswordChangeRequired, mountedRef, refresh, requestStepUp]);
}

function ProviderStepUpModal({ mgr, t }: { mgr: ReturnType<typeof useStepUpManager>; t: Translate }) {
  return (
    <StepUpDialog
      isOpen={mgr.isStepUpOpen}
      onSuccess={() => mgr.resolveStepUp(true)}
      onCancel={() => mgr.resolveStepUp(false)}
      t={t}
    />
  );
}

function buildContextValue(
  state: ReturnType<typeof useAuthStateManager>,
  actions: ReturnType<typeof useAuthActions>,
  requestStepUp: () => Promise<boolean>
): AuthContextValue {
  return {
    status: state.status,
    user: state.user,
    roles: state.roles,
    permissions: state.permissions,
    csrf: state.csrf,
    mustChangePassword: state.mustChangePassword,
    login: actions.login,
    logout: actions.logout,
    refresh: actions.refresh,
    requestStepUp,
  };
}

export function AuthProvider({ children, t = defaultTranslate }: AuthProviderProps) {
  const state = useAuthStateManager();
  const stepUpMgr = useStepUpManager();
  const actions = useAuthActions(state.applySession, state.clearSession);

  useAuthLifecycle(stepUpMgr.requestStepUp, state, actions.refresh, state.mountedRef);
  const contextValue = buildContextValue(state, actions, stepUpMgr.requestStepUp);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
      <ProviderStepUpModal mgr={stepUpMgr} t={t} />
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

function evaluateCan(status: AuthStatus, permissions: readonly string[], permission: string): CanResult {
  if (status === "disabled") {
    return { allowed: true, reason: "" };
  }
  if (status !== "authenticated") {
    return { allowed: false, reason: "auth.reason.not_authenticated" };
  }
  if (permissions.includes(permission)) {
    return { allowed: true, reason: "" };
  }
  if (!KNOWN_PERMISSIONS.has(permission)) {
    return { allowed: false, reason: "auth.reason.unknown_permission" };
  }
  return {
    allowed: false,
    reason: "auth.reason.requires_role",
    requiredRole: PERMISSION_LOWEST_ROLE[permission],
  };
}

/** Checks one permission for the current session (everything is allowed when auth is off). */
export function useCan(permission: string): CanResult {
  const { status, permissions } = useAuth();
  return evaluateCan(status, permissions, permission);
}

/** Returns a checker for several permissions at once (use when the set is not fixed at render). */
export function useCanCheck(): (permission: string) => CanResult {
  const { status, permissions } = useAuth();
  return (permission) => evaluateCan(status, permissions, permission);
}
