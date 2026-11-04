"""Local user store for ADR 013: the ``_auth/users.json`` document.

Reads and writes user records validated against ``schemas/auth-users.schema.json``.
Writes are validated before touching disk and replace the file atomically; reads
are cached and revalidated whenever the file's stat changes.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import tempfile
import threading
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from crosscut_api.auth.lockout import to_iso

AUTH_FOLDER = "_auth"
USERS_FILE = "users.json"
SCHEMA_FILE = "auth-users.schema.json"
SCHEMA_ENV = "CROSSCUT_SCHEMAS_DIR"
DOCUMENT_VERSION = 1
_MESSAGE_KEYWORDS = frozenset({"required", "additionalProperties"})


class UserStoreError(ValueError):
    """Base error for user store failures."""


class NotInitialisedError(UserStoreError):
    """Raised when the users file does not exist yet."""


class UsersFileError(UserStoreError):
    """Raised when the users file is not valid JSON or fails the schema."""


class UserExistsError(UserStoreError):
    """Raised when creating a username that already exists."""


class UserNotFoundError(UserStoreError):
    """Raised when a username is not present in the store."""


def auth_dir(root: Path) -> Path:
    """Return the auth folder beneath a data root."""
    return root / AUTH_FOLDER


def users_path(root: Path) -> Path:
    """Return the users file path beneath a data root."""
    return auth_dir(root) / USERS_FILE


def new_user_record(
    username: str,
    display_name: str,
    roles: list[str],
    password: dict[str, Any],
    now: float,
) -> dict[str, Any]:
    """Build a schema-valid user record for a freshly set password.

    Args:
        username: Unique login name matching the schema pattern.
        display_name: Human-readable name.
        roles: Assigned role names; must be non-empty and unique.
        password: scrypt record as returned by ``passwords.hash_password``.
        now: Creation time as POSIX timestamp.

    Returns:
        A user record ready for ``UserStore.create``.
    """
    stamp = to_iso(now)
    return {
        "username": username,
        "display_name": display_name,
        "roles": list(roles),
        "disabled": False,
        "must_change_password": False,
        "password": dict(password),
        "created_at": stamp,
        "password_changed_at": stamp,
        "failed_logins": 0,
        "locked_until": None,
        "source": "local",
    }


class UserStore(Protocol):
    """Storage interface for user records."""

    def initialised(self) -> bool:
        """Return ``True`` when the users file exists."""
        ...

    def get(self, username: str) -> dict[str, Any] | None:
        """Return a copy of one user record, or ``None`` when absent."""
        ...

    def list_users(self) -> list[dict[str, Any]]:
        """Return copies of all user records."""
        ...

    def create(self, user: dict[str, Any]) -> None:
        """Append a user record; raises ``UserExistsError`` for a duplicate name."""
        ...

    def update(self, username: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Shallow-merge top-level fields into a user and return the new record."""
        ...

    def delete(self, username: str) -> None:
        """Remove a user; raises ``UserNotFoundError`` when absent."""
        ...

    def write_all(self, users: list[dict[str, Any]]) -> None:
        """Replace every user, creating the users file when it is missing."""
        ...


def _schema_path() -> Path:
    """Return the users schema path, honouring the ``CROSSCUT_SCHEMAS_DIR`` override."""
    override = os.environ.get(SCHEMA_ENV)
    base = Path(override) if override else Path(__file__).resolve().parents[4] / "schemas"
    return base / SCHEMA_FILE


@functools.lru_cache(maxsize=4)
def _validator_for(schema_file: str) -> Draft202012Validator:
    """Compile and cache the users schema validator for a schema file path."""
    schema = json.loads(Path(schema_file).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _location(path: Iterable[object]) -> str:
    """Render an error path such as ``users[0].password`` for messages."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text or "(document)"


def _describe(error: ValidationError) -> str:
    """Describe one schema violation without echoing instance values (hashes stay out)."""
    where = _location(error.absolute_path)
    if error.validator in _MESSAGE_KEYWORDS:
        return f"{where}: {error.message}"
    return f"{where}: failed '{error.validator}' check"


def _duplicate_problems(document: Any) -> list[str]:
    """Report every username that appears more than once in the users list."""
    users = document.get("users") if isinstance(document, dict) else None
    if not isinstance(users, list):
        return []
    names = [user.get("username") for user in users if isinstance(user, dict)]
    counts = Counter(name for name in names if isinstance(name, str))
    return [f"users: duplicate username '{name}'" for name, n in sorted(counts.items()) if n > 1]


def _problems(document: Any) -> list[str]:
    """Return all schema and uniqueness problems of a users document; empty when valid."""
    validator = _validator_for(str(_schema_path()))
    schema_problems = [_describe(error) for error in validator.iter_errors(document)]
    return schema_problems + _duplicate_problems(document)


def _ensure_valid(document: Any) -> None:
    """Raise ``UsersFileError`` listing the problems of an invalid users document."""
    problems = _problems(document)
    if problems:
        raise UsersFileError("users file failed validation: " + "; ".join(problems))


def _read_file(path: Path) -> dict[str, Any]:
    """Read, parse and validate the users file; missing or invalid files raise."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise NotInitialisedError(f"{path} does not exist; run the user CLI init.") from exc
    except UnicodeDecodeError as exc:
        raise UsersFileError(f"{path.name} is not valid UTF-8.") from exc
    try:
        document: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsersFileError(f"{path.name} is not valid JSON (line {exc.lineno}).") from exc
    _ensure_valid(document)
    return document


def _write(path: Path, document: dict[str, Any]) -> None:
    """Write a JSON document atomically; the temp file is owner-only on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        if os.name == "posix":
            os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _index_of(users: list[Any], username: object) -> int | None:
    """Return the position of a username in the users list, or ``None``."""
    for index, user in enumerate(users):
        if isinstance(user, dict) and user.get("username") == username:
            return index
    return None


def _require_index(users: list[Any], username: str) -> int:
    """Return the position of a username, raising ``UserNotFoundError`` when absent."""
    index = _index_of(users, username)
    if index is None:
        raise UserNotFoundError(f"user {username!r} not found")
    return index


class JsonUserStore:
    """User store backed by ``<root>/_auth/users.json`` with a stat-keyed read cache."""

    def __init__(self, root: Path) -> None:
        """Bind the store to a data root; the file is not touched until first use."""
        self._path = users_path(root)
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_key: tuple[int, int] | None = None

    def initialised(self) -> bool:
        """Return ``True`` when the users file exists."""
        return self._path.exists()

    def get(self, username: str) -> dict[str, Any] | None:
        """Return a copy of one user record, or ``None`` when absent or uninitialised."""
        try:
            users = self._load()["users"]
        except NotInitialisedError:
            return None
        index = _index_of(users, username)
        return None if index is None else copy.deepcopy(users[index])

    def list_users(self) -> list[dict[str, Any]]:
        """Return copies of all user records; raises ``NotInitialisedError`` if missing."""
        return copy.deepcopy(self._load()["users"])

    def create(self, user: dict[str, Any]) -> None:
        """Append a user record; raises ``UserExistsError`` for a duplicate name."""
        with self._lock:
            document = copy.deepcopy(self._load())
            name = user.get("username")
            if _index_of(document["users"], name) is not None:
                raise UserExistsError(f"user {name!r} already exists")
            document["users"].append(copy.deepcopy(user))
            self._commit(document)

    def update(self, username: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Shallow-merge top-level fields into a user and return the new record."""
        with self._lock:
            document = copy.deepcopy(self._load())
            index = _require_index(document["users"], username)
            document["users"][index].update(copy.deepcopy(changes))
            self._commit(document)
            return copy.deepcopy(document["users"][index])

    def delete(self, username: str) -> None:
        """Remove a user; raises ``UserNotFoundError`` when absent."""
        with self._lock:
            document = copy.deepcopy(self._load())
            del document["users"][_require_index(document["users"], username)]
            self._commit(document)

    def write_all(self, users: list[dict[str, Any]]) -> None:
        """Replace every user, creating the users file when it is missing."""
        with self._lock:
            self._commit({"version": DOCUMENT_VERSION, "users": copy.deepcopy(users)})

    def _stat_key(self) -> tuple[int, int]:
        """Return the (mtime_ns, size) pair of the users file; missing raises."""
        try:
            stat = self._path.stat()
        except FileNotFoundError as exc:
            raise NotInitialisedError(f"{self._path} does not exist.") from exc
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self) -> dict[str, Any]:
        """Return the validated document, re-reading it only when its stat changed."""
        key = self._stat_key()
        if self._cache is not None and key == self._cache_key:
            return self._cache
        document = _read_file(self._path)
        self._cache, self._cache_key = document, key
        return document

    def _commit(self, document: dict[str, Any]) -> None:
        """Validate a full document, then atomically replace the users file."""
        _ensure_valid(document)
        _write(self._path, document)
        self._cache = None
        self._cache_key = None
