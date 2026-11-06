// frontend/src/components/RoleBadge.tsx
/**
 * Header status badge displaying the signed-in user, their assigned roles, and logout button.
 * Accessible, resilient to long usernames, and renders plain text without HTML injection.
 */

import { useAuth } from "../AuthContext";
import type { AuthUser } from "../authApi";
import type { Translate } from "../findings";

export interface RoleBadgeProps {
  t: Translate;
  user?: AuthUser | null;
  roles?: string[];
  onLogout?: () => void | Promise<void>;
}

interface RoleChipsListProps {
  roles: string[];
  t: Translate;
}

function RoleChipsList({ roles, t }: RoleChipsListProps) {
  return (
    <div
      className="role-badge-chips"
      data-testid="role-badge-chips"
      style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}
    >
      {roles.map((role) => (
        <span key={role} className="status-chip status-chip--ok">
          {t(`auth.role.${role}`) || role}
        </span>
      ))}
    </div>
  );
}

function UserNameDisplay({ user }: { user: AuthUser }) {
  const name = user.display_name.trim() ? user.display_name : user.username;
  const style = {
    fontWeight: 600,
    maxWidth: 160,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap" as const,
  };
  return (
    <span className="role-badge-user" data-testid="role-badge-user" style={style} title={user.username}>
      {name}
    </span>
  );
}

function LogoutButton({ onClick, label }: { onClick: () => void | Promise<void>; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="role-badge-logout"
      data-testid="role-badge-logout"
      style={{ padding: "4px 8px" }}
    >
      {label}
    </button>
  );
}

interface ContextAuth {
  user: AuthUser | null;
  roles: string[];
  logout: () => Promise<void>;
}

/** Reads the auth context, or null when rendered outside an AuthProvider. */
function useOptionalAuth(): ContextAuth | null {
  try {
    const auth = useAuth();
    return { user: auth.user, roles: auth.roles, logout: auth.logout };
  } catch {
    return null;
  }
}

function useResolvedAuth(props: RoleBadgeProps) {
  const ctx = useOptionalAuth();
  return {
    user: props.user ?? ctx?.user ?? null,
    roles: props.roles ?? ctx?.roles ?? [],
    onLogout: props.onLogout ?? ctx?.logout,
  };
}

export function RoleBadge({ t, user, roles, onLogout }: RoleBadgeProps) {
  const resolved = useResolvedAuth({ t, user, roles, onLogout });
  if (!resolved.user) return null;

  return (
    <div
      className="role-badge"
      role="region"
      aria-label={t("auth.userBadge")}
      style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap", maxWidth: "100%" }}
    >
      <UserNameDisplay user={resolved.user} />
      <RoleChipsList roles={resolved.roles} t={t} />
      {resolved.onLogout && <LogoutButton onClick={resolved.onLogout} label={t("auth.logout")} />}
    </div>
  );
}
