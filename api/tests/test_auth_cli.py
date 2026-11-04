"""Tests for the crosscut_api.auth_cli bootstrap commands (ADR 013).

Runs init, add-user, set-password and rotate-key in-process and checks the files they write,
their exit codes, and that passwords and key bytes never reach the console or the audit log.
"""

import json
import stat
import sys
from pathlib import Path

import pytest
from crosscut_api.auth.audit import AuthAudit
from crosscut_api.auth.passwords import verify_password
from crosscut_api.auth.store import JsonUserStore, auth_dir, users_path
from crosscut_api.auth_cli import AUDIT_FILE, KEY_BYTES, KEY_FILE, main
from jsonschema import Draft202012Validator

PASSWORD = "correct horse 1"
NEW_PASSWORD = "another horse 2"
SHORT_PASSWORD = "short1"
SCHEMA_FILE = Path(__file__).resolve().parents[2] / "schemas" / "auth-users.schema.json"


@pytest.fixture(autouse=True)
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test a fast scrypt cost and a secrets folder under tmp_path."""
    monkeypatch.setenv("CROSSCUT_AUTH_SCRYPT_N", "1024")
    monkeypatch.setenv("CROSSCUT_SECRETS_DIR", str(tmp_path / "sec"))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Return the data root that holds _auth/ for the CLI."""
    return tmp_path / "data"


@pytest.fixture
def pw_file(tmp_path: Path) -> Path:
    """Return a password file holding PASSWORD."""
    return _write_password(tmp_path, "pw.txt", PASSWORD)


def _write_password(tmp_path: Path, name: str, password: str) -> Path:
    """Write password plus a line ending to tmp_path/name and return the path."""
    path = tmp_path / name
    path.write_text(password + "\n", encoding="utf-8")
    return path


def _key(tmp_path: Path) -> Path:
    """Return the gateway key path inside the test secrets folder."""
    return tmp_path / "sec" / KEY_FILE


def _init(root: Path, pw_file: Path) -> int:
    """Run the init command with the given password file."""
    return main(["init", "--root", str(root), "--password-file", str(pw_file)])


def _add(root: Path, pw_file: Path, username: str, roles: str) -> int:
    """Run add-user for username with a comma-separated role list."""
    return main([
        "add-user", "--root", str(root), "--username", username,
        "--roles", roles, "--password-file", str(pw_file),
    ])


def test_init_writes_schema_valid_admin_store(root: Path, pw_file: Path) -> None:
    """Init writes one admin account with the admin role and a verifiable password."""
    assert _init(root, pw_file) == 0
    document = json.loads(users_path(root).read_text(encoding="utf-8"))
    Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))).validate(document)
    [admin] = document["users"]
    assert admin["username"] == "admin"
    assert admin["roles"] == ["admin"]
    assert verify_password(PASSWORD, admin["password"])


def test_init_creates_key_and_audit_chain(root: Path, pw_file: Path, tmp_path: Path) -> None:
    """Init writes a 32-byte gateway key and a verifiable audit chain with one cli_init event."""
    assert _init(root, pw_file) == 0
    assert len(_key(tmp_path).read_bytes()) == KEY_BYTES
    audit = AuthAudit(auth_dir(root) / AUDIT_FILE)
    assert audit.verify()
    assert [record["event"] for record in audit.records()] == ["cli_init"]


def test_init_twice_is_rejected_and_changes_nothing(
    root: Path, pw_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second init exits 2 and leaves users.json and the key unchanged."""
    _init(root, pw_file)
    users_before = users_path(root).read_bytes()
    key_before = _key(tmp_path).read_bytes()
    capsys.readouterr()
    assert _init(root, pw_file) == 2
    assert users_path(root).read_bytes() == users_before
    assert _key(tmp_path).read_bytes() == key_before
    assert "already initialised" in capsys.readouterr().err


def test_init_short_password_writes_nothing(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A password below the policy minimum exits 2 and creates neither users.json nor a key."""
    short = _write_password(tmp_path, "short.txt", SHORT_PASSWORD)
    assert _init(root, short) == 2
    assert not users_path(root).exists()
    assert not _key(tmp_path).exists()
    assert "error:" in capsys.readouterr().err


def test_init_keeps_existing_key_file(
    root: Path, pw_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Init reuses an existing gateway key file byte for byte."""
    existing = bytes(range(KEY_BYTES))
    _key(tmp_path).parent.mkdir(parents=True)
    _key(tmp_path).write_bytes(existing)
    assert _init(root, pw_file) == 0
    assert _key(tmp_path).read_bytes() == existing
    assert "kept existing" in capsys.readouterr().out


def test_add_user_creates_login_able_account(root: Path, pw_file: Path) -> None:
    """Add-user stores the requested roles and a password that verifies."""
    _init(root, pw_file)
    assert _add(root, pw_file, "ops.jan", "operator,engineer") == 0
    user = JsonUserStore(root).get("ops.jan")
    assert user is not None
    assert user["roles"] == ["operator", "engineer"]
    assert verify_password(PASSWORD, user["password"])


def test_add_user_unknown_role_is_rejected(root: Path, pw_file: Path) -> None:
    """A role missing from the role table exits 2 and the user is not stored."""
    _init(root, pw_file)
    assert _add(root, pw_file, "ops.jan", "wizard") == 2
    assert JsonUserStore(root).get("ops.jan") is None


def test_add_user_duplicate_is_rejected(root: Path, pw_file: Path) -> None:
    """Adding an existing username exits 2 and keeps the original record."""
    _init(root, pw_file)
    before = JsonUserStore(root).get("admin")
    assert _add(root, pw_file, "admin", "viewer") == 2
    assert JsonUserStore(root).get("admin") == before


def test_add_user_before_init_is_rejected(root: Path, pw_file: Path) -> None:
    """Add-user on a root without users.json exits 2 and creates no users file."""
    assert _add(root, pw_file, "ops.jan", "operator") == 2
    assert not users_path(root).exists()


def test_set_password_replaces_hash_and_clears_lock(
    root: Path, pw_file: Path, tmp_path: Path
) -> None:
    """Set-password swaps the hash and resets failed_logins and locked_until."""
    _init(root, pw_file)
    old_hash = JsonUserStore(root).get("admin")["password"]["hash_b64"]
    JsonUserStore(root).update(
        "admin", {"failed_logins": 3, "locked_until": "2099-01-01T00:00:00Z"}
    )
    new_pw = _write_password(tmp_path, "new.txt", NEW_PASSWORD)
    code = main(["set-password", "--root", str(root), "--username", "admin",
                 "--password-file", str(new_pw)])
    assert code == 0
    user = JsonUserStore(root).get("admin")
    assert user["password"]["hash_b64"] != old_hash
    assert user["failed_logins"] == 0
    assert user["locked_until"] is None
    assert verify_password(NEW_PASSWORD, user["password"])


def test_set_password_unknown_user_is_rejected(root: Path, pw_file: Path) -> None:
    """Set-password for a username that does not exist exits 2."""
    _init(root, pw_file)
    code = main(["set-password", "--root", str(root), "--username", "nobody",
                 "--password-file", str(pw_file)])
    assert code == 2


def test_rotate_key_replaces_key_bytes(root: Path, pw_file: Path, tmp_path: Path) -> None:
    """Rotate-key writes new 32-byte key material in place of the old key."""
    _init(root, pw_file)
    before = _key(tmp_path).read_bytes()
    assert main(["rotate-key", "--root", str(root)]) == 0
    after = _key(tmp_path).read_bytes()
    assert len(after) == KEY_BYTES
    assert after != before


def test_audit_and_console_hold_no_password_or_key_bytes(
    root: Path, pw_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Audit file and console output omit the passwords and key bytes, old or new."""
    new_pw = _write_password(tmp_path, "new.txt", NEW_PASSWORD)
    old_key = b""
    base = ["--root", str(root)]
    steps = [
        (["init", *base, "--password-file", str(pw_file)], 0),
        (["add-user", *base, "--username", "ops.jan", "--roles", "operator",
          "--password-file", str(pw_file)], 0),
        (["set-password", *base, "--username", "ops.jan", "--password-file", str(new_pw)], 0),
        (["rotate-key", *base], 0),
    ]
    for argv, expected in steps:
        assert main(argv) == expected
        out, err = capsys.readouterr()
        assert PASSWORD not in out + err and NEW_PASSWORD not in out + err
        if argv[0] == "init":
            old_key = _key(tmp_path).read_bytes()
    raw = (auth_dir(root) / AUDIT_FILE).read_bytes()
    text = raw.decode("utf-8")
    new_key = _key(tmp_path).read_bytes()
    for secret in (PASSWORD, NEW_PASSWORD, old_key.hex(), new_key.hex()):
        assert secret not in text
    assert old_key not in raw and new_key not in raw
    assert AuthAudit(auth_dir(root) / AUDIT_FILE).verify()


def test_secrets_default_to_root_underscore_secrets(
    root: Path, pw_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without CROSSCUT_SECRETS_DIR the key goes to <root>/_secrets."""
    monkeypatch.delenv("CROSSCUT_SECRETS_DIR")
    assert _init(root, pw_file) == 0
    assert (root / "_secrets" / KEY_FILE).stat().st_size == KEY_BYTES


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_posix_key_and_users_file_modes(root: Path, pw_file: Path, tmp_path: Path) -> None:
    """The key is group-readable at most (0o640) and users.json is owner-only (0o600)."""
    _init(root, pw_file)
    key_mode = stat.S_IMODE(_key(tmp_path).stat().st_mode)
    assert key_mode & 0o077 <= 0o040
    assert key_mode == 0o640
    assert stat.S_IMODE(users_path(root).stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="icacls hints are printed on Windows")
def test_windows_init_prints_icacls_hints(
    root: Path, pw_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On Windows, init prints icacls commands to restrict the users and key files."""
    assert _init(root, pw_file) == 0
    assert "icacls" in capsys.readouterr().out
