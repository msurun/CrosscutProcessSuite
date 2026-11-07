"""Command-line bootstrap and user administration for local auth (ADR 013).

Creates the first admin, users.json and the gateway HMAC key, adds users, resets
passwords and rotates the key. Passwords, hashes and key bytes are never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.lockout import success_changes, to_iso
from crosscut_api.auth.passwords import hash_password, password_problem
from crosscut_api.auth.roles import RolesError, load_roles
from crosscut_api.auth.sessions import AuthConfig
from crosscut_api.auth.settings import AuthSettingsError, load_auth_config
from crosscut_api.auth.store import (
    JsonUserStore,
    NotInitialisedError,
    UserExistsError,
    UserNotFoundError,
    UserStoreError,
    auth_dir,
    new_user_record,
    users_path,
)

SECRETS_ENV = "CROSSCUT_SECRETS_DIR"
SCRYPT_ENV = "CROSSCUT_AUTH_SCRYPT_N"
KEY_FILE = "gateway-hmac.key"
KEY_BYTES = 32
KEY_MODE = 0o640
SECRETS_DIR_MODE = 0o750
MIN_SCRYPT_N = 1024
AUDIT_FILE = "auth-audit.jsonl"
ADMIN_ROLES = ["admin"]
USERNAME_RE = re.compile(r"[a-z][a-z0-9._-]{2,31}")
EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2


class CliUsageError(Exception):
    """A problem with the command or its inputs; reported with exit code 2."""


def _auth_config(root: Path | None = None) -> AuthConfig:
    """Return the site auth configuration, applying the CROSSCUT_AUTH_SCRYPT_N override."""
    try:
        base = load_auth_config(root, AuthConfig())
    except AuthSettingsError as exc:
        raise CliUsageError(str(exc)) from exc
    raw = os.environ.get(SCRYPT_ENV)
    if raw is None:
        return base
    return replace(base, scrypt=replace(base.scrypt, n=_parse_scrypt_n(raw)))


def _parse_scrypt_n(raw: str) -> int:
    """Validate the scrypt cost override: an integer, a power of two, at least 1024."""
    try:
        n = int(raw)
    except ValueError as exc:
        raise CliUsageError(f"{SCRYPT_ENV} must be an integer") from exc
    if n < MIN_SCRYPT_N or n & (n - 1):
        raise CliUsageError(f"{SCRYPT_ENV} must be a power of two >= {MIN_SCRYPT_N}")
    return n


def _username(raw: str) -> str:
    """Return the username when it matches the schema pattern, else raise a usage error."""
    if USERNAME_RE.fullmatch(raw) is None:
        raise CliUsageError("username must match [a-z][a-z0-9._-]{2,31}")
    return raw


def _read_first_line(path: Path) -> str:
    """Return the first line of a password file without its line ending."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise CliUsageError(f"cannot read password file {path}") from exc
    lines = text.splitlines()
    return lines[0] if lines else ""


def _prompt_password() -> str:
    """Ask for the password twice and return it when both entries match."""
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise CliUsageError("passwords do not match")
    return first


def _read_password(password_file: str | None, min_length: int) -> str:
    """Return a password from a file or a prompt, enforcing the password policy."""
    if password_file:
        password = _read_first_line(Path(password_file))
    else:
        password = _prompt_password()
    problem = password_problem(password, min_length)
    if problem is not None:
        raise CliUsageError(problem)
    return password


def _require_initialised(store: JsonUserStore) -> None:
    """Raise a usage error when users.json does not exist yet."""
    if not store.initialised():
        raise CliUsageError("not initialised; run `init` first")


def _roles_arg(raw: str, root: Path) -> list[str]:
    """Split a comma-separated role list and check every name against the role table."""
    roles = [part.strip() for part in raw.split(",") if part.strip()]
    if not roles:
        raise CliUsageError("at least one role is required")
    if len(set(roles)) != len(roles):
        raise CliUsageError("roles must not repeat")
    table = load_roles(root)
    unknown = [role for role in roles if not table.known(role)]
    if unknown:
        known = ", ".join(table.names())
        raise CliUsageError(f"unknown role(s): {', '.join(unknown)}; known roles: {known}")
    return roles


def secrets_dir(root: Path) -> Path:
    """Return the secrets folder: CROSSCUT_SECRETS_DIR when set, else <root>/_secrets."""
    override = os.environ.get(SECRETS_ENV)
    return Path(override) if override else root / "_secrets"


def key_path(root: Path) -> Path:
    """Return the path of the gateway HMAC key file."""
    return secrets_dir(root) / KEY_FILE


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Replace path with data through a temp file in the same folder."""
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        if os.name == "posix":
            os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _write_key(path: Path) -> None:
    """Atomically write fresh random key bytes; the secrets folder is restricted on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path.parent, SECRETS_DIR_MODE)
    _atomic_write(path, os.urandom(KEY_BYTES), KEY_MODE)


def _ensure_key(root: Path) -> bool:
    """Create the gateway key when absent; return True when created, False when kept."""
    path = key_path(root)
    if path.exists():
        return False
    _write_key(path)
    return True


def _audit(root: Path, event: str, **fields: str) -> None:
    """Append one CLI event to the hash-chained auth audit log."""
    AuthAudit(auth_dir(root) / AUDIT_FILE).append(event, actor="cli", **fields)


def _print_icacls_hints(paths: list[Path]) -> None:
    """On Windows, print the icacls command that restricts each path to the current user."""
    if os.name != "nt":
        return
    for path in paths:
        print(f'icacls "{path}" /inheritance:r /grant:r "%USERNAME%:(R,W)"')


def _new_record(args: argparse.Namespace, root: Path, roles: list[str]) -> dict[str, object]:
    """Build a user record with a hashed password read from the arguments."""
    config = _auth_config(root)
    username = _username(args.username)
    password = _read_password(args.password_file, config.min_password_length)
    return new_user_record(
        username,
        args.display_name or username,
        roles,
        hash_password(password, config.scrypt),
        time.time(),
    )


def cmd_init(args: argparse.Namespace) -> int:
    """Create users.json with the first admin and the gateway key when absent."""
    root = Path(args.root)
    if users_path(root).exists():
        raise CliUsageError(f"already initialised: {users_path(root)} exists")
    record = _new_record(args, root, ADMIN_ROLES)
    JsonUserStore(root).write_all([record])
    created = _ensure_key(root)
    _audit(root, "cli_init", username=str(record["username"]))
    key = key_path(root)
    print("initialised")
    print(f"  admin account: {record['username']} (roles: admin)")
    print(f"  users file: {users_path(root)}")
    print(f"  gateway key: {'created' if created else 'kept existing'} {key}")
    print("  admin carries no process authority; add the roles people need with add-user")
    _print_icacls_hints([users_path(root), key])
    return EXIT_OK


def cmd_add_user(args: argparse.Namespace) -> int:
    """Add a user with validated roles and a freshly hashed password."""
    root = Path(args.root)
    store = JsonUserStore(root)
    _require_initialised(store)
    username = _username(args.username)
    roles = _roles_arg(args.roles, root)
    if store.get(username) is not None:
        raise CliUsageError(f"user {username!r} already exists")
    record = _new_record(args, root, roles)
    record["must_change_password"] = bool(args.must_change_password)
    store.create(record)
    _audit(root, "cli_add_user", username=username, roles=",".join(roles))
    print(f"added user {username} (roles: {', '.join(roles)})")
    return EXIT_OK


def cmd_set_password(args: argparse.Namespace) -> int:
    """Replace a user's password and clear failure counters and any lock."""
    root = Path(args.root)
    store = JsonUserStore(root)
    _require_initialised(store)
    username = _username(args.username)
    if store.get(username) is None:
        raise CliUsageError(f"user {username!r} not found")
    config = _auth_config(root)
    password = _read_password(args.password_file, config.min_password_length)
    store.update(
        username,
        {
            **success_changes(),
            "password": hash_password(password, config.scrypt),
            "password_changed_at": to_iso(time.time()),
            "must_change_password": False,
        },
    )
    _audit(root, "cli_set_password", username=username)
    print(f"password set for {username}")
    print("sessions already open stay valid until the API restarts or they time out")
    return EXIT_OK


def cmd_rotate_key(args: argparse.Namespace) -> int:
    """Replace the gateway HMAC key with fresh random bytes."""
    root = Path(args.root)
    path = key_path(root)
    _write_key(path)
    _audit(root, "cli_rotate_key")
    print(f"rotated gateway key: {path}")
    print("restart the gateway and the API now; commands signed with the old key are rejected")
    _print_icacls_hints([path])
    return EXIT_OK


def _add_init_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser],
                     common: argparse.ArgumentParser) -> None:
    """Register the init subcommand and its options."""
    init = commands.add_parser(
        "init", parents=[common], help="create the first admin, users.json and the gateway key"
    )
    init.add_argument("--username", default="admin")
    init.add_argument("--display-name")
    init.add_argument("--password-file")


def _add_user_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser],
                      common: argparse.ArgumentParser) -> None:
    """Register the add-user, set-password and rotate-key subcommands."""
    add = commands.add_parser("add-user", parents=[common], help="add a user")
    add.add_argument("--username", required=True)
    add.add_argument("--roles", required=True, help="comma-separated role names")
    add.add_argument("--display-name")
    add.add_argument("--password-file")
    add.add_argument("--must-change-password", action="store_true")
    reset = commands.add_parser("set-password", parents=[common], help="reset a password")
    reset.add_argument("--username", required=True)
    reset.add_argument("--password-file")
    commands.add_parser("rotate-key", parents=[common], help="replace the gateway HMAC key")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree; every subcommand requires --root."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, required=True, help="data root that holds _auth/")
    parser = argparse.ArgumentParser(
        prog="python -m crosscut_api.auth_cli",
        description="Local auth bootstrap and user administration (ADR 013).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    _add_init_parser(commands, common)
    _add_user_parsers(commands, common)
    return parser


_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "init": cmd_init,
    "add-user": cmd_add_user,
    "set-password": cmd_set_password,
    "rotate-key": cmd_rotate_key,
}


def main(argv: list[str] | None = None) -> int:
    """Run one auth CLI command and return its exit code (0 ok, 2 user error, 1 unexpected)."""
    args = _build_parser().parse_args(argv)
    try:
        return _HANDLERS[args.command](args)
    except (CliUsageError, UserExistsError, UserNotFoundError, NotInitialisedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (UserStoreError, RolesError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
