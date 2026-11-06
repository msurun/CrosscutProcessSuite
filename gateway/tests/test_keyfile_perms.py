"""Tests for the key file permission check in crosscut_gateway.keyfile."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from crosscut_gateway import keyfile

KEY = b"s" * 32


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (0o600, None),
        (0o620, "key_file_group_or_world_writable"),
        (0o660, "key_file_group_or_world_writable"),
        (0o666, "key_file_group_or_world_writable"),
        (0o604, "key_file_world_readable"),
        (0o644, "key_file_world_readable"),
    ],
)
def test_mode_problem(mode: int, expected: str | None) -> None:
    assert keyfile.mode_problem(mode) == expected


def test_acl_status_unchecked_when_not_posix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(keyfile, "_IS_POSIX", False)
    assert keyfile.key_acl_status(tmp_path / "missing.key") == "unchecked"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_private_key_file_is_read(tmp_path: Path) -> None:
    path = tmp_path / "gateway-hmac.key"
    path.write_bytes(KEY)
    path.chmod(0o600)
    assert keyfile.read_key(path) == KEY
    assert keyfile.key_acl_status(path) == "ok"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
@pytest.mark.parametrize("mode", [0o644, 0o660, 0o666])
def test_loose_key_file_is_refused(tmp_path: Path, mode: int) -> None:
    path = tmp_path / "gateway-hmac.key"
    path.write_bytes(KEY)
    path.chmod(mode)
    assert keyfile.read_key(path) is None
    assert keyfile.key_acl_status(path) == "insecure"


def test_write_key_file_helper_yields_an_accepted_key(tmp_path: Path) -> None:
    """The shared test helper must always produce a key file the gateway accepts."""
    from auth_helpers import write_key_file

    path = write_key_file(tmp_path / "_secrets" / "gateway-hmac.key", KEY)
    assert keyfile.read_key(path) == KEY
    assert keyfile.key_permission_problem(path) is None
