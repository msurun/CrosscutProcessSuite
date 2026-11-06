// frontend/src/usersForms.tsx
/**
 * Modal forms for the user administration console: create user, edit roles, reset password and
 * delete confirmation. Forms validate client-side and stay open with the server error on failure.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, MIN_PASSWORD_LENGTH } from "./authApi";
import type { CreateUserPayload, UserRecord } from "./authApi";
import { ModalDialog } from "./components/ModalDialog";
import type { Translate } from "./findings";

export const ALL_ROLES = ["viewer", "operator", "engineer", "lead", "admin"] as const;
export const USERNAME_PATTERN = /^[a-z][a-z0-9._-]{2,31}$/;

const DANGER_STYLE = { color: "#d32f2f" };
const FIELD_ERROR_STYLE = { color: "#d32f2f", display: "block", fontSize: "0.85em" };
const BUTTON_ROW_STYLE = { display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 };

/** Formats a failed request the same way for the page banner and the modal that issued it. */
export function errorText(t: Translate, err: unknown): string {
  return t("auth.users.error", { detail: err instanceof ApiError ? err.detail : "Error" });
}

/** Returns the localised problem with a password, or undefined when it is acceptable. */
export function passwordProblem(password: string, t: Translate): string | undefined {
  return password.length >= MIN_PASSWORD_LENGTH ? undefined : t("auth.users.passwordTooShort", { min: MIN_PASSWORD_LENGTH });
}

interface CreateValues {
  username: string;
  displayName: string;
  password: string;
  roles: string[];
}

interface CreateErrors {
  username?: string;
  displayName?: string;
  password?: string;
  roles?: string;
}

/** Validates the create form fields; an empty object means the form may be submitted. */
export function validateCreate(v: CreateValues, t: Translate): CreateErrors {
  const errors: CreateErrors = {};
  if (!USERNAME_PATTERN.test(v.username)) errors.username = t("auth.users.usernameInvalid");
  if (!v.displayName.trim()) errors.displayName = t("auth.users.displayNameRequired");
  if (v.roles.length === 0) errors.roles = t("auth.users.rolesRequired");
  const pwd = passwordProblem(v.password, t);
  if (pwd) errors.password = pwd;
  return errors;
}

function useModalAction(action: () => Promise<void>, onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (t: Translate) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err: unknown) {
      setError(errorText(t, err));
      setBusy(false);
      return;
    }
    onDone();
  };
  return { busy, error, run };
}

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return <span id={id} role="alert" style={FIELD_ERROR_STYLE}>{message}</span>;
}

function ModalError({ message }: { message: string | null }) {
  if (!message) return null;
  return <p role="alert" data-testid="modal-error" style={FIELD_ERROR_STYLE}>{message}</p>;
}

interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  type?: string;
}

function TextField({ id, label, value, onChange, error, type = "text" }: TextFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div style={{ marginBottom: 8 }}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        style={{ display: "block", marginTop: 4, width: "100%", boxSizing: "border-box" }}
      />
      <FieldError id={errorId} message={error} />
    </div>
  );
}

interface RoleCheckboxListProps {
  selectedRoles: string[];
  onChange: (roles: string[]) => void;
  t: Translate;
}

export function RoleCheckboxList({ selectedRoles, onChange, t }: RoleCheckboxListProps) {
  const toggle = (r: string) => onChange(selectedRoles.includes(r) ? selectedRoles.filter((x) => x !== r) : [...selectedRoles, r]);
  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "6px 0" }}>
      {ALL_ROLES.map((role) => (
        <label key={role} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={selectedRoles.includes(role)} onChange={() => toggle(role)} data-testid={`role-checkbox-${role}`} />
          <span>{t(`auth.role.${role}`)}</span>
        </label>
      ))}
    </div>
  );
}

interface ButtonRowProps {
  onClose: () => void;
  busy: boolean;
  submit: { label: string; testId: string; type: "submit" | "button"; onClick?: () => void; disabled?: boolean; danger?: boolean };
  t: Translate;
}

function ButtonRow({ onClose, busy, submit, t }: ButtonRowProps) {
  return (
    <div style={BUTTON_ROW_STYLE}>
      <button type="button" onClick={onClose} disabled={busy}>{t("auth.users.cancel")}</button>
      <button type={submit.type} onClick={submit.onClick} disabled={busy || submit.disabled} data-testid={submit.testId} style={submit.danger ? DANGER_STYLE : undefined}>
        {submit.label}
      </button>
    </div>
  );
}

export interface CreateUserModalProps {
  onCreate: (payload: CreateUserPayload) => Promise<void>;
  onClose: () => void;
  t: Translate;
}

/** Modal form creating a user; closes only when the server accepted the request. */
export function CreateUserModal({ onCreate, onClose, t }: CreateUserModalProps) {
  const [v, setV] = useState<CreateValues>({ username: "", displayName: "", password: "", roles: ["viewer"] });
  const [mustChange, setMustChange] = useState(true);
  const [submitted, setSubmitted] = useState(false);
  const payload: CreateUserPayload = { username: v.username, display_name: v.displayName.trim(), roles: v.roles, password: v.password, must_change_password: mustChange };
  const { busy, error, run } = useModalAction(() => onCreate(payload), onClose);
  const errors = submitted ? validateCreate(v, t) : {};
  const patch = (p: Partial<CreateValues>) => setV({ ...v, ...p });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (Object.keys(validateCreate(v, t)).length === 0) void run(t);
  };

  return (
    <ModalDialog title={t("auth.users.createTitle")} onClose={onClose} busy={busy} testId="create-user-dialog">
      <form onSubmit={handleSubmit} noValidate>
        <TextField id="create-username" label={t("auth.users.username")} value={v.username} onChange={(x) => patch({ username: x })} error={errors.username} />
        <TextField id="create-display-name" label={t("auth.users.displayName")} value={v.displayName} onChange={(x) => patch({ displayName: x })} error={errors.displayName} />
        <TextField id="create-password" type="password" label={t("auth.users.password")} value={v.password} onChange={(x) => patch({ password: x })} error={errors.password} />
        <RoleCheckboxList selectedRoles={v.roles} onChange={(roles) => patch({ roles })} t={t} />
        <FieldError id="create-roles-error" message={errors.roles} />
        <label style={{ display: "block", marginTop: 8 }}>
          <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />{" "}
          <span>{t("auth.users.mustChangePassword")}</span>
        </label>
        <ModalError message={error} />
        <ButtonRow onClose={onClose} busy={busy} t={t} submit={{ label: t("auth.users.createButton"), testId: "create-user-submit", type: "submit" }} />
      </form>
    </ModalDialog>
  );
}

export interface EditRolesModalProps {
  user: UserRecord;
  onSave: (username: string, roles: string[]) => Promise<void>;
  onClose: () => void;
  t: Translate;
}

/** Modal editing the roles of one user. */
export function EditRolesModal({ user, onSave, onClose, t }: EditRolesModalProps) {
  const [roles, setRoles] = useState<string[]>(user.roles);
  const { busy, error, run } = useModalAction(() => onSave(user.username, roles), onClose);
  return (
    <ModalDialog title={`${t("auth.users.editRoles")}: ${user.username}`} onClose={onClose} busy={busy} testId="edit-roles-dialog">
      <RoleCheckboxList selectedRoles={roles} onChange={setRoles} t={t} />
      {roles.length === 0 && <FieldError id="edit-roles-error" message={t("auth.users.rolesRequired")} />}
      <ModalError message={error} />
      <ButtonRow onClose={onClose} busy={busy} t={t} submit={{ label: t("auth.users.save"), testId: "save-roles-button", type: "button", onClick: () => void run(t), disabled: roles.length === 0 }} />
    </ModalDialog>
  );
}

export interface ResetPasswordModalProps {
  user: UserRecord;
  onSave: (username: string, password: string) => Promise<void>;
  onClose: () => void;
  t: Translate;
}

/** Modal letting an administrator set a new password for another user. */
export function ResetPasswordModal({ user, onSave, onClose, t }: ResetPasswordModalProps) {
  const [password, setPassword] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const { busy, error, run } = useModalAction(() => onSave(user.username, password), onClose);
  const problem = submitted ? passwordProblem(password, t) : undefined;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (!passwordProblem(password, t)) void run(t);
  };

  return (
    <ModalDialog title={`${t("auth.users.resetPassword")}: ${user.username}`} onClose={onClose} busy={busy} testId="reset-password-dialog">
      <form onSubmit={handleSubmit} noValidate>
        <TextField id="reset-pwd-input" type="password" label={t("auth.users.password")} value={password} onChange={setPassword} error={problem} />
        <ModalError message={error} />
        <ButtonRow onClose={onClose} busy={busy} t={t} submit={{ label: t("auth.users.save"), testId: "save-reset-pwd-button", type: "submit" }} />
      </form>
    </ModalDialog>
  );
}

export interface DeleteConfirmModalProps {
  username: string;
  onConfirm: (username: string) => Promise<void>;
  onClose: () => void;
  t: Translate;
}

/** Confirmation dialog before deleting a user account. */
export function DeleteConfirmModal({ username, onConfirm, onClose, t }: DeleteConfirmModalProps) {
  const { busy, error, run } = useModalAction(() => onConfirm(username), onClose);
  return (
    <ModalDialog title={t("auth.users.delete")} onClose={onClose} busy={busy} testId="delete-user-dialog">
      <p>{t("auth.users.deleteConfirm", { username })}</p>
      <ModalError message={error} />
      <ButtonRow onClose={onClose} busy={busy} t={t} submit={{ label: t("auth.users.delete"), testId: "confirm-delete-button", type: "button", onClick: () => void run(t), danger: true }} />
    </ModalDialog>
  );
}
