"""Adversarial inbox file path and name attack tests for Write Gateway.

Evaluates directory traversal attempts, reserved operating system names, long and unicode
filenames, concurrent file modifications, and symlink/junction injections into the inbox.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import (
    AuthEnv,
    make_env,
    outbox,
    propose_args,
    signed,
)

ALLOWED_ROOT_SUBDIRS = frozenset({"_gateway", "_secrets"})


def _assert_path_invariants(root: Path, valid_cmd_id: str) -> None:
    """In plain words: Assert nothing was written outside _gateway and valid command succeeded."""
    top_entries = {entry.name for entry in root.iterdir()}
    leaked = top_entries - ALLOWED_ROOT_SUBDIRS
    assert not leaked, f"Security violation: files leaked outside gateway root: {leaked}"
    valid_result = outbox(root, valid_cmd_id)
    assert valid_result is not None and valid_result["ok"] is True, (
        f"Valid command {valid_cmd_id} was dropped or failed during path attack cycle!"
    )


def _drop_valid_command(env: AuthEnv, tag: str = "valid") -> str:
    """In plain words: Drop an authentic signed command into inbox for concurrent processing."""
    valid_env = signed(
        env,
        "propose",
        propose_args(env, 55.0),
        actor="alice",
        roles=("engineer",),
    )
    inbox = env.root / "_gateway" / "inbox"
    (inbox / f"{tag}_{valid_env['id']}.json").write_text(json.dumps(valid_env), encoding="utf-8")
    return str(valid_env["id"])


def test_dot_dot_filenames_in_inbox_do_not_escape(tmp_path: Path) -> None:
    """In plain words: Inbox files whose names contain '..' must stay confined to _gateway."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"

    # Craft filenames containing parent directory tokens
    dot_names = ["..dots_start.json", "middle..dots.json", "..json"]
    for name in dot_names:
        (inbox / name).write_text('{"bad": "json', encoding="utf-8")

    valid_id = _drop_valid_command(env, "dot_test")
    env.service.poll_once()
    _assert_path_invariants(env.root, valid_id)


def test_windows_reserved_filenames_do_not_crash(tmp_path: Path) -> None:
    """In plain words: Windows device names like CON and NUL must not crash or hang poll_once."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"

    reserved_names = ["CON.json", "NUL.json", "AUX.json", "PRN.json", "COM1.json"]
    for name in reserved_names:
        try:
            (inbox / name).write_text("invalid json", encoding="utf-8")
        except OSError:
            pass  # Some Windows platforms may block creating specific reserved names directly

    valid_id = _drop_valid_command(env, "reserved_test")
    env.service.poll_once()
    _assert_path_invariants(env.root, valid_id)


def test_long_and_unicode_filenames_do_not_crash(tmp_path: Path) -> None:
    """In plain words: Extreme filename lengths and unicode scripts must be handled gracefully."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"

    long_filename = ("a" * 200) + ".json"
    unicode_filename = "команда_🚀_ñandú_測試.json"

    for name in (long_filename, unicode_filename):
        try:
            (inbox / name).write_text('{"id": "x"}', encoding="utf-8")
        except OSError:
            pass

    valid_id = _drop_valid_command(env, "long_unicode_test")
    env.service.poll_once()
    _assert_path_invariants(env.root, valid_id)


def test_command_id_path_traversal_is_rejected(tmp_path: Path) -> None:
    """In plain words: A command id with directory traversal or slashes must not escape outbox."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"

    traversal_ids = ["../escaped_outbox", r"..\win_escaped", "col:on", "/absolute/leak"]
    for index, bad_id in enumerate(traversal_ids):
        payload = {"id": bad_id, "cmd": "kill", "args": {}}
        (inbox / f"bad_id_{index}.json").write_text(json.dumps(payload), encoding="utf-8")

    valid_id = _drop_valid_command(env, "id_traversal_test")
    env.service.poll_once()
    _assert_path_invariants(env.root, valid_id)


def _create_junction_or_symlink(target_dir: Path, link_path: Path) -> bool:
    """In plain words: Attempt to create an OS junction or directory symlink, returning success."""
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(target_dir), str(link_path))
            return True
        except (OSError, ImportError):
            pass
    try:
        os.symlink(target_dir, link_path, target_is_directory=True)
        return True
    except OSError:
        return False


def test_symlink_or_junction_inside_inbox_confined(tmp_path: Path) -> None:
    """In plain words: An inbox link to an external directory must not delete or leak files."""
    gw_root = tmp_path / "gw_root"
    gw_root.mkdir()
    env = make_env(gw_root)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir(parents=True, exist_ok=True)
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("critical_system_data", encoding="utf-8")

    junc_path = env.root / "_gateway" / "inbox" / "junc.json"
    created = _create_junction_or_symlink(outside_dir, junc_path)
    if not created:
        pytest.skip("Operating system cannot create symlinks or junctions without elevation")

    valid_id = _drop_valid_command(env, "symlink_test")
    env.service.poll_once()

    # Crucial check: external target directory and file must remain completely intact
    assert secret_file.exists()
    assert secret_file.read_text(encoding="utf-8") == "critical_system_data"
    _assert_path_invariants(env.root, valid_id)


def test_two_files_with_same_id_in_same_poll(tmp_path: Path) -> None:
    """In plain words: Two distinct files claiming identical command id are cleanly deduplicated."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"

    shared_id = "duplicate_id_001"
    env1 = signed(
        env,
        "propose",
        propose_args(env, 55.0),
        actor="alice",
        roles=("engineer",),
        extra=signed.__wrapped__.__code__.co_varnames if False else None,  # type: ignore[attr-defined]
    )
    # Ensure both envelopes share the exact same id
    env1["id"] = shared_id
    env2 = copy_signed_with_new_nonce(env, env1)

    (inbox / "file_a.json").write_text(json.dumps(env1), encoding="utf-8")
    (inbox / "file_b.json").write_text(json.dumps(env2), encoding="utf-8")

    env.service.poll_once()

    # Outbox should have the result for the first, rejected folder should contain the second
    rejected_dir = env.root / "_gateway" / "rejected"
    assert (rejected_dir / "file_b.json").exists() or (rejected_dir / "file_a.json").exists()
    out = outbox(env.root, shared_id)
    assert out is not None and out["ok"] is True


def copy_signed_with_new_nonce(env: AuthEnv, base_env: dict[str, Any]) -> dict[str, Any]:
    """In plain words: Create another signed envelope with the same id but a fresh nonce."""
    from crosscut_gateway.envelope import sign_envelope

    new_env = json.loads(json.dumps(base_env))
    new_env["auth"]["nonce"] = "f" * 32
    new_env.pop("sig", None)
    return sign_envelope(new_env, env.service._gate.key)


def test_file_growing_while_read_does_not_crash_poll(tmp_path: Path) -> None:
    """In plain words: Incomplete JSON written incrementally to inbox does not crash poll_once."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"

    # Write truncated JSON simulating in-progress write
    (inbox / "growing.json").write_text('{"id": "grow1", "cmd": "prop', encoding="utf-8")

    valid_id = _drop_valid_command(env, "growing_test")
    env.service.poll_once()

    # The growing file must be moved to rejected, and the valid command must succeed
    assert (env.root / "_gateway" / "rejected" / "growing.json").exists()
    _assert_path_invariants(env.root, valid_id)
