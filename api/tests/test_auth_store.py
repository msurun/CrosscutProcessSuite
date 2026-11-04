"""Tests for crosscut_api.auth.store: the JsonUserStore lifecycle and new_user_record.

Covers uninitialised reads, copy semantics, validated atomic writes, the stat-keyed cache,
schema compliance of the written document and the absence of leftover temp files.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from crosscut_api.auth.passwords import ScryptParams, hash_password
from crosscut_api.auth.store import (
    SCHEMA_ENV,
    JsonUserStore,
    NotInitialisedError,
    UserExistsError,
    UserNotFoundError,
    UsersFileError,
    new_user_record,
    users_path,
)
from jsonschema import Draft202012Validator

PARAMS = ScryptParams(n=1024)
PASSWORD = "correct horse battery"
NOW = 0.0
SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schemas" / "auth-users.schema.json"
SECRET_HASH = "LEAKSENTINELHASHVALUE"


@pytest.fixture(autouse=True)
def _default_schema_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the store resolve the repository schema, not an inherited override."""
    monkeypatch.delenv(SCHEMA_ENV, raising=False)


def _record(username: str, roles: tuple[str, ...] = ("viewer",)) -> dict[str, Any]:
    """Return a schema-valid user record with a low-cost scrypt password."""
    password = hash_password(PASSWORD, PARAMS)
    return new_user_record(username, username.title(), list(roles), password, NOW)


def _document(*users: dict[str, Any]) -> dict[str, Any]:
    """Wrap user records in a versioned users document."""
    return {"version": 1, "users": list(users)}


def _usernames(users: list[dict[str, Any]]) -> list[str]:
    """Return the usernames of a list of user records, in order."""
    return [user["username"] for user in users]


def test_uninitialised_store_reports_missing_file(tmp_path: Path) -> None:
    """A store over an empty root reports not initialised and returns no user."""
    store = JsonUserStore(tmp_path)
    assert store.initialised() is False
    assert store.get("alice") is None


def test_uninitialised_store_list_and_create_raise(tmp_path: Path) -> None:
    """list_users and create raise NotInitialisedError and do not create the file."""
    store = JsonUserStore(tmp_path)
    with pytest.raises(NotInitialisedError):
        store.list_users()
    with pytest.raises(NotInitialisedError):
        store.create(_record("alice"))
    assert not users_path(tmp_path).exists()


def test_write_all_then_read_returns_copies(tmp_path: Path) -> None:
    """Mutating records returned by get or list_users never changes the stored users."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice"), _record("bob")])
    assert store.initialised() is True
    fetched = store.get("alice")
    fetched["roles"].append("admin")
    fetched["failed_logins"] = 99
    assert store.get("alice")["roles"] == ["viewer"]
    assert store.get("alice")["failed_logins"] == 0
    listed = store.list_users()
    listed[1]["display_name"] = "Changed"
    assert _usernames(listed) == ["alice", "bob"]
    assert store.get("bob")["display_name"] == "Bob"
    assert store.get("carol") is None


def test_create_appends_and_rejects_duplicate(tmp_path: Path) -> None:
    """create appends a new user and raises UserExistsError for an existing name."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    store.create(_record("bob"))
    assert _usernames(store.list_users()) == ["alice", "bob"]
    with pytest.raises(UserExistsError):
        store.create(_record("alice", roles=("admin",)))
    assert store.get("alice")["roles"] == ["viewer"]


def test_update_merges_fields_and_persists(tmp_path: Path) -> None:
    """update shallow-merges the given fields, returns the new record and writes it to disk."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    changes = {"failed_logins": 3, "locked_until": "2026-11-03T12:00:00Z"}
    updated = store.update("alice", changes)
    assert updated["failed_logins"] == 3
    assert updated["locked_until"] == "2026-11-03T12:00:00Z"
    assert updated["display_name"] == "Alice"
    reopened = JsonUserStore(tmp_path).get("alice")
    assert reopened["failed_logins"] == 3
    assert reopened["locked_until"] == "2026-11-03T12:00:00Z"
    assert reopened["roles"] == ["viewer"]


def test_update_and_delete_unknown_user_raise(tmp_path: Path) -> None:
    """update and delete of a username that is not stored raise UserNotFoundError."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    with pytest.raises(UserNotFoundError):
        store.update("nobody", {"failed_logins": 1})
    with pytest.raises(UserNotFoundError):
        store.delete("nobody")


def test_delete_removes_user_and_persists(tmp_path: Path) -> None:
    """delete removes only the named user and the removal survives a fresh store."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice"), _record("bob")])
    store.delete("alice")
    assert store.get("alice") is None
    assert _usernames(JsonUserStore(tmp_path).list_users()) == ["bob"]


def test_external_rewrite_is_picked_up_by_cache(tmp_path: Path) -> None:
    """A users file rewritten outside the store is re-read once its mtime or size changes."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    assert store.get("alice") is not None
    path = users_path(tmp_path)
    before = path.stat()
    path.write_text(json.dumps(_document(_record("bob"))), encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    after = path.stat()
    assert (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size)
    assert store.get("alice") is None
    assert _usernames(store.list_users()) == ["bob"]


def test_invalid_external_document_raises_without_leaking_hash(tmp_path: Path) -> None:
    """An externally written invalid document raises UsersFileError without echoing hashes."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    bad = _record("alice")
    bad["roles"] = []
    bad["password"]["hash_b64"] = SECRET_HASH
    users_path(tmp_path).write_text(json.dumps(_document(bad)), encoding="utf-8")
    with pytest.raises(UsersFileError) as info:
        store.get("alice")
    assert "roles" in str(info.value)
    assert SECRET_HASH not in str(info.value)


def test_invalid_update_raises_and_leaves_file_identical(tmp_path: Path) -> None:
    """An update that breaks the schema raises UsersFileError and the file is not touched."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    before = users_path(tmp_path).read_bytes()
    with pytest.raises(UsersFileError):
        store.update("alice", {"roles": []})
    assert users_path(tmp_path).read_bytes() == before
    assert store.get("alice")["roles"] == ["viewer"]


def test_written_file_validates_against_schema(tmp_path: Path) -> None:
    """The users file written by the store has no violations of auth-users.schema.json."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice"), _record("bob", roles=("admin", "operator"))])
    document = json.loads(users_path(tmp_path).read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(document)) == []
    assert document["version"] == 1


def test_no_temp_files_left_behind(tmp_path: Path) -> None:
    """After a sequence of writes the _auth folder holds only the users file."""
    store = JsonUserStore(tmp_path)
    store.write_all([_record("alice")])
    store.create(_record("bob"))
    store.update("alice", {"failed_logins": 1})
    store.delete("bob")
    names = sorted(path.name for path in (tmp_path / "_auth").iterdir())
    assert names == ["users.json"]


def test_new_user_record_fields() -> None:
    """new_user_record sets the defaults, ISO timestamps and copies its roles and password."""
    password = hash_password(PASSWORD, PARAMS)
    roles = ["viewer"]
    record = new_user_record("alice", "Alice", roles, password, NOW)
    roles.append("admin")
    assert record["roles"] == ["viewer"]
    assert record["disabled"] is False
    assert record["must_change_password"] is False
    assert record["source"] == "local"
    assert record["locked_until"] is None
    assert record["failed_logins"] == 0
    assert record["created_at"] == "1970-01-01T00:00:00Z"
    assert record["password_changed_at"] == record["created_at"]
    assert record["password"] == password
