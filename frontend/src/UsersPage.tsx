// frontend/src/UsersPage.tsx
/**
 * User administration console for administrators (requires users.manage permission).
 * Lists system accounts and opens modal forms (see usersForms.tsx) for create, roles, reset, delete.
 */

import { useCallback, useEffect, useState } from "react";
import type { ReactElement } from "react";
import { createUser, deleteUser, fetchUsers, patchUser, type UserRecord } from "./authApi";
import { useAuth, useCan } from "./AuthContext";
import { DisabledReason } from "./components/DisabledReason";
import type { Translate } from "./findings";
import {
  CreateUserModal,
  DeleteConfirmModal,
  EditRolesModal,
  ResetPasswordModal,
  errorText,
} from "./usersForms";

export { ALL_ROLES } from "./usersForms";

export interface UsersPageProps {
  t: Translate;
}

type Mutate = (action: () => Promise<unknown>) => Promise<void>;

interface RowHandlers {
  onEditRoles: (u: UserRecord) => void;
  onToggleDisabled: (u: UserRecord) => void;
  onResetPassword: (u: UserRecord) => void;
  onDelete: (u: UserRecord) => void;
}

interface ActionButtonsProps extends RowHandlers {
  user: UserRecord;
  isSelf: boolean;
  t: Translate;
}

function SelfGuarded({ isSelf, reason, t, children }: { isSelf: boolean; reason: string; t: Translate; children: ReactElement }) {
  return <DisabledReason disabled={isSelf} reason={reason} t={t}>{children}</DisabledReason>;
}

function UserActionButtons({ user, isSelf, onEditRoles, onToggleDisabled, onResetPassword, onDelete, t }: ActionButtonsProps) {
  const name = user.username;
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      <SelfGuarded isSelf={isSelf} reason={t("auth.users.cannotEditOwnRoles")} t={t}>
        <button type="button" onClick={() => onEditRoles(user)} data-testid={`edit-roles-${name}`}>{t("auth.users.editRoles")}</button>
      </SelfGuarded>
      <SelfGuarded isSelf={isSelf} reason={t("auth.users.cannotDisableSelf")} t={t}>
        <button type="button" onClick={() => onToggleDisabled(user)} data-testid={`toggle-disabled-${name}`}>
          {user.disabled ? t("auth.users.enable") : t("auth.users.disable")}
        </button>
      </SelfGuarded>
      <SelfGuarded isSelf={isSelf} reason={t("auth.users.cannotResetSelf")} t={t}>
        <button type="button" onClick={() => onResetPassword(user)} data-testid={`reset-pwd-${name}`}>{t("auth.users.resetPassword")}</button>
      </SelfGuarded>
      <SelfGuarded isSelf={isSelf} reason={t("auth.users.cannotDeleteSelf")} t={t}>
        <button type="button" onClick={() => onDelete(user)} data-testid={`delete-${name}`} style={{ color: "#d32f2f" }}>{t("auth.users.delete")}</button>
      </SelfGuarded>
    </div>
  );
}

function UserRolesCell({ roles, t }: { roles: string[]; t: Translate }) {
  return (
    <td>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {roles.map((r) => (
          <span key={r} className="status-chip status-chip--ok">{t(`auth.role.${r}`) || r}</span>
        ))}
      </div>
    </td>
  );
}

/** True when the account has a lockout end time in the future. */
export function isLocked(user: UserRecord, now: number = Date.now()): boolean {
  if (!user.locked_until) return false;
  const until = Date.parse(user.locked_until);
  return Number.isFinite(until) && until > now;
}

function StatusChip({ kind, text }: { kind: "ok" | "problem" | "warning"; text: string }) {
  return <span className={`status-chip status-chip--${kind}`} style={{ marginRight: 4 }}>{text}</span>;
}

function UserStatusCell({ user, t }: { user: UserRecord; t: Translate }) {
  return (
    <td>
      <StatusChip kind={user.disabled ? "problem" : "ok"} text={user.disabled ? t("auth.status.disabled") : t("auth.status.active")} />
      {user.must_change_password && <StatusChip kind="warning" text={t("auth.status.mustChangePassword")} />}
      {isLocked(user) && <StatusChip kind="problem" text={t("auth.users.locked")} />}
    </td>
  );
}

interface UserRowProps extends RowHandlers {
  user: UserRecord;
  currentUsername: string | null;
  t: Translate;
}

function UserTableRow(props: UserRowProps) {
  const { user, currentUsername, t } = props;
  return (
    <tr data-testid={`user-row-${user.username}`}>
      <td style={{ fontWeight: 600 }}>{user.username}</td>
      <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>{user.display_name}</td>
      <UserRolesCell roles={user.roles} t={t} />
      <UserStatusCell user={user} t={t} />
      <td><UserActionButtons {...props} isSelf={user.username === currentUsername} /></td>
    </tr>
  );
}

function UsersTableHeader({ t }: { t: Translate }) {
  const keys = ["username", "displayName", "roles", "status", "actions"];
  return (
    <thead>
      <tr style={{ borderBottom: "2px solid var(--color-border, #ccc)", textAlign: "left" }}>
        {keys.map((k) => <th key={k} style={{ padding: "8px 4px" }}>{t(`auth.users.${k}`)}</th>)}
      </tr>
    </thead>
  );
}

interface UsersPageTableProps extends RowHandlers {
  users: UserRecord[];
  currentUsername: string | null;
  t: Translate;
}

function UsersPageTable(props: UsersPageTableProps) {
  const { users, t } = props;
  return (
    <div style={{ overflowX: "auto", maxWidth: "100%" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <UsersTableHeader t={t} />
        <tbody>
          {users.length === 0 && <tr><td colSpan={5} style={{ padding: 16, textAlign: "center" }}>{t("auth.users.empty")}</td></tr>}
          {users.map((u) => <UserTableRow key={u.username} {...props} user={u} />)}
        </tbody>
      </table>
    </div>
  );
}

/** Loads users and wraps mutations: the banner is set on failure and the error is rethrown. */
function useUsersManager(t: Translate) {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    try {
      setUsers((await fetchUsers()).users);
      setError(null);
    } catch (err: unknown) {
      setError(errorText(t, err));
    }
  }, [t]);

  const mutate: Mutate = async (action) => {
    try {
      await action();
    } catch (err: unknown) {
      setError(errorText(t, err));
      throw err;
    }
    await loadUsers();
  };

  const mutateQuiet = (action: () => Promise<unknown>) => mutate(action).catch(() => undefined);
  return { users, error, loadUsers, mutate, mutateQuiet };
}

type ModalState =
  | { kind: "create" }
  | { kind: "roles"; user: UserRecord }
  | { kind: "reset"; user: UserRecord }
  | { kind: "delete"; username: string }
  | null;

interface UsersPageModalsProps {
  modal: ModalState;
  onClose: () => void;
  mutate: Mutate;
  t: Translate;
}

function UsersPageModals({ modal, onClose, mutate, t }: UsersPageModalsProps) {
  if (!modal) return null;
  if (modal.kind === "create") {
    return <CreateUserModal onCreate={(p) => mutate(() => createUser(p))} onClose={onClose} t={t} />;
  }
  if (modal.kind === "roles") {
    return <EditRolesModal user={modal.user} onSave={(u, r) => mutate(() => patchUser(u, { roles: r }))} onClose={onClose} t={t} />;
  }
  if (modal.kind === "reset") {
    return <ResetPasswordModal user={modal.user} onSave={(u, p) => mutate(() => patchUser(u, { password: p, must_change_password: true }))} onClose={onClose} t={t} />;
  }
  return <DeleteConfirmModal username={modal.username} onConfirm={(u) => mutate(() => deleteUser(u))} onClose={onClose} t={t} />;
}

function UsersPageHeader({ t, error, onCreate }: { t: Translate; error: string | null; onCreate: () => void }) {
  return (
    <>
      <h1 style={{ marginBottom: 4 }}>{t("auth.users.title")}</h1>
      <p style={{ color: "var(--color-muted, #666)", marginBottom: 20 }}>{t("auth.users.subtitle")}</p>
      {error && <div className="notice notice-warning" role="alert" style={{ marginBottom: 16 }}><p>{error}</p></div>}
      <button type="button" onClick={onCreate} data-testid="open-create-user" style={{ marginBottom: 16 }}>{t("auth.users.createTitle")}</button>
    </>
  );
}

/** Administrator console listing accounts with create, role, reset, disable and delete actions. */
export function UsersPage({ t }: UsersPageProps) {
  const { user: me } = useAuth();
  const { allowed } = useCan("users.manage");
  const { users, error, loadUsers, mutate, mutateQuiet } = useUsersManager(t);
  const [modal, setModal] = useState<ModalState>(null);

  useEffect(() => {
    if (allowed) void loadUsers();
  }, [allowed, loadUsers]);

  if (!allowed) {
    return <div className="notice notice-warning" role="alert"><p>{t("auth.users.denied")}</p></div>;
  }

  return (
    <div className="users-page" style={{ maxWidth: 960, margin: "20px auto", padding: "0 16px", boxSizing: "border-box" }}>
      <UsersPageHeader t={t} error={error} onCreate={() => setModal({ kind: "create" })} />
      <UsersPageTable
        users={users}
        currentUsername={me?.username ?? null}
        onEditRoles={(user) => setModal({ kind: "roles", user })}
        onToggleDisabled={(u) => void mutateQuiet(() => patchUser(u.username, { disabled: !u.disabled }))}
        onResetPassword={(user) => setModal({ kind: "reset", user })}
        onDelete={(u) => setModal({ kind: "delete", username: u.username })}
        t={t}
      />
      <UsersPageModals modal={modal} onClose={() => setModal(null)} mutate={mutate} t={t} />
    </div>
  );
}
