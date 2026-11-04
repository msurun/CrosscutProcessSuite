"""Tests for the auth JSON schemas in schemas/.

Checks that the shipped default roles document validates against its schema, that a
well-formed users document is accepted, and that malformed documents are rejected.
JSON files are loaded lazily inside helpers so collection survives missing files.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
ROLES_SCHEMA_PATH = SCHEMAS / "auth-roles.schema.json"
USERS_SCHEMA_PATH = SCHEMAS / "auth-users.schema.json"
ROLES_DEFAULT_PATH = SCHEMAS / "auth-roles.default.json"


def _load_json(path):
    """Read a JSON file from disk and return the parsed document."""
    return json.loads(path.read_text(encoding="utf-8"))


def _roles_validator():
    """Return a Draft202012Validator for the roles schema."""
    return Draft202012Validator(_load_json(ROLES_SCHEMA_PATH))


def _users_validator():
    """Return a Draft202012Validator for the users schema."""
    return Draft202012Validator(_load_json(USERS_SCHEMA_PATH))


def _password_doc():
    """Return a valid password sub-document."""
    return {
        "alg": "scrypt",
        "n": 1024,
        "r": 8,
        "p": 1,
        "salt_b64": "c2FsdHNhbHRzYWx0",
        "hash_b64": "aGFzaGhhc2hoYXNo",
    }


def _valid_user_doc():
    """Return a valid single-user document for the users schema."""
    return {
        "username": "alice.ops",
        "display_name": "Alice Ops",
        "roles": ["operator"],
        "disabled": False,
        "must_change_password": False,
        "password": _password_doc(),
        "created_at": "2026-11-01T08:00:00Z",
        "password_changed_at": "2026-11-01T08:00:00Z",
        "failed_logins": 0,
        "locked_until": None,
        "source": "local",
    }


def _users_doc():
    """Return a valid users document (version 1) wrapping one user."""
    return {"version": 1, "users": [_valid_user_doc()]}


def _roles_doc(roles):
    """Return a valid roles document (version 1) with the given roles mapping."""
    return {"version": 1, "roles": roles}


def test_default_roles_doc_validates_against_roles_schema():
    """The shipped auth-roles.default.json is accepted by the roles schema."""
    default_json = _load_json(ROLES_DEFAULT_PATH)
    assert _roles_validator().is_valid(default_json) is True


def test_valid_users_doc_validates_against_users_schema():
    """A well-formed users document is accepted by the users schema."""
    assert _users_validator().is_valid(_users_doc()) is True


@pytest.mark.parametrize("bad_role_name", ["Bad-Name"])
def test_roles_doc_with_bad_role_name_is_rejected(bad_role_name):
    """Role names must match the permitted identifier pattern."""
    doc = _roles_doc({bad_role_name: {"permissions": ["gw.status"]}})
    assert _roles_validator().is_valid(doc) is False


def test_roles_doc_with_unknown_top_level_key_is_rejected():
    """Unknown top-level keys are not allowed in a roles document."""
    doc = _roles_doc({"operator": {"permissions": ["gw.status"]}})
    doc["unexpected"] = 1
    assert _roles_validator().is_valid(doc) is False


def test_roles_doc_with_unknown_role_key_is_rejected():
    """Unknown keys inside a role are not allowed."""
    doc = _roles_doc({"operator": {"permissions": ["gw.status"], "extra": True}})
    assert _roles_validator().is_valid(doc) is False


def test_roles_doc_with_unknown_permission_is_rejected():
    """Permission ids must be drawn from the known catalog."""
    doc = _roles_doc({"operator": {"permissions": ["gw.fly"]}})
    assert _roles_validator().is_valid(doc) is False


def test_roles_doc_with_inherits_key_is_rejected():
    """A role may not declare an 'inherits' relationship."""
    doc = _roles_doc({"operator": {"permissions": ["gw.status"], "inherits": ["admin"]}})
    assert _roles_validator().is_valid(doc) is False


def test_users_doc_with_unknown_top_level_key_is_rejected():
    """Unknown top-level keys are not allowed in a users document."""
    doc = _users_doc()
    doc["unexpected"] = 1
    assert _users_validator().is_valid(doc) is False


def test_users_doc_with_unknown_user_key_is_rejected():
    """Unknown keys inside a user entry are not allowed."""
    doc = _users_doc()
    doc["users"][0]["unexpected"] = 1
    assert _users_validator().is_valid(doc) is False


def test_users_doc_with_unknown_password_key_is_rejected():
    """Unknown keys inside the password entry are not allowed."""
    doc = _users_doc()
    doc["users"][0]["password"]["unexpected"] = 1
    assert _users_validator().is_valid(doc) is False


@pytest.mark.parametrize(
    "bad_username",
    ["Alice.ops", "al", "1alice", "a" * 33],
)
def test_users_doc_with_bad_username_is_rejected(bad_username):
    """Usernames must be lowercase, start with a letter and be 3-32 chars."""
    doc = _users_doc()
    doc["users"][0]["username"] = bad_username
    assert _users_validator().is_valid(doc) is False


def test_users_doc_with_small_scrypt_n_is_rejected():
    """The scrypt cost parameter n must meet the minimum."""
    doc = _users_doc()
    doc["users"][0]["password"]["n"] = 512
    assert _users_validator().is_valid(doc) is False


def test_users_doc_with_empty_roles_is_rejected():
    """A user must have at least one role."""
    doc = _users_doc()
    doc["users"][0]["roles"] = []
    assert _users_validator().is_valid(doc) is False


def test_users_doc_with_integer_locked_until_is_rejected():
    """locked_until must be a timestamp string or null, never an integer."""
    doc = _users_doc()
    doc["users"][0]["locked_until"] = 5
    assert _users_validator().is_valid(doc) is False


def test_default_equals_load_roles():
    """load_roles(None) equals the roles mapping parsed from the default JSON."""
    from crosscut_gateway.authz import load_roles

    default_json = _load_json(ROLES_DEFAULT_PATH)
    expected = {
        name: frozenset(role["permissions"])
        for name, role in default_json["roles"].items()
    }
    assert load_roles(None) == expected
