"""Adversarial inbox file path and name attack tests for Write Gateway.

Evaluates directory traversal attempts, reserved operating system names, long and unicode
filenames, concurrent file modifications, and symlink/junction injections into the inbox.
Every test walks the whole temp tree afterwards and compares it to an allow-list.
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
    SignOpts,
    audit_events,
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    signed,
)

GATEWAY_FILES = frozenset({"state.json", "nonce-cache.json", "policy-draft.json", "KILLED"})
SERVICE_DIRS = frozenset({"inbox", "outbox", "rejected"})
RESULT_SUFFIXES = (".json", ".json.reason.txt")


def _unexpected_paths(base: Path, root: Path, tolerated: tuple[Path, ...] = ()) -> list[str]:
    """In plain words: Walk base (without following links) and list paths outside the allow-list.

    Allowed under ``root``: ``_secrets/<key file>`` and ``_gateway`` holding the three service
    folders (with plain files only), plus a few known state files. Anything under a tolerated
    prefix (a test's own fixtures) is skipped.
    """
    bad: list[str] = []
    for current, dirs, files in os.walk(base, followlinks=False):
        here = Path(current)
        if any(here == t or t in here.parents for t in tolerated):
            dirs.clear()
            continue
        for name in [*dirs, *files]:
            path = here / name
            if any(path == t for t in tolerated):
                continue
            if not _is_allowed(path, root, is_dir=name in dirs):
                bad.append(str(path.relative_to(base)))
    return bad


def _is_allowed(path: Path, root: Path, *, is_dir: bool) -> bool:
    """In plain words: Decide whether one path under the gateway root is an expected artifact."""
    if path == root:
        return True
    if root not in path.parents:
        return False  # anything beside the gateway root is a leak
    parts = path.relative_to(root).parts
    if parts[0] == "_secrets":
        return len(parts) == 1 or (len(parts) == 2 and not is_dir)
    if parts[0] != "_gateway":
        return False
    if len(parts) == 1:
        return True
    if len(parts) == 2:
        return (is_dir and parts[1] in SERVICE_DIRS) or (
            not is_dir and parts[1] in GATEWAY_FILES
        )
    return len(parts) == 3 and parts[1] in SERVICE_DIRS and path.name.endswith(RESULT_SUFFIXES)


def _assert_confined(
    root: Path, valid_cmd_id: str, base: Path | None = None, tolerated: tuple[Path, ...] = ()
) -> None:
    """In plain words: Nothing sits outside the gateway folders and the valid command succeeded."""
    leaked = _unexpected_paths(base or root, root, tolerated)
    assert not leaked, f"Security violation: unexpected paths in the tree: {leaked}"
    valid_result = outbox(root, valid_cmd_id)
    assert valid_result is not None and valid_result["ok"] is True, (
        f"Valid command {valid_cmd_id} was dropped or failed during path attack cycle!"
    )


def _drop_valid_command(env: AuthEnv, tag: str = "valid") -> str:
    """In plain words: Drop an authentic signed command into inbox for concurrent processing."""
    valid_env = signed(
        env, "propose", propose_args(env, 55.0), actor="alice", roles=("engineer",)
    )
    inbox = env.root / "_gateway" / "inbox"
    (inbox / f"{tag}_{valid_env['id']}.json").write_text(json.dumps(valid_env), encoding="utf-8")
    return str(valid_env["id"])


def _assert_moved_to_rejected(env: AuthEnv, name: str, reason_prefix: str | None = None) -> None:
    """In plain words: The named inbox file left the inbox and sits in rejected/ with a reason."""
    assert not (env.root / "_gateway" / "inbox" / name).exists(), f"{name} stayed in inbox"
    assert (env.root / "_gateway" / "rejected" / name).exists(), f"{name} not in rejected/"
    if reason_prefix is not None:
        reason = rejected_reason(env.root, name.removesuffix(".json"))
        assert reason is not None and reason.startswith(reason_prefix), (name, reason)


def _write_names(inbox: Path, names: list[str], text: str) -> list[str]:
    """In plain words: Create the files the platform allows; return the names that were written."""
    written = []
    for name in names:
        try:
            (inbox / name).write_text(text, encoding="utf-8")
        except OSError:
            continue  # the platform blocks this name outright
        written.append(name)
    return written


def test_dot_dot_filenames_in_inbox_do_not_escape(tmp_path: Path) -> None:
    """In plain words: Inbox files whose names contain '..' must stay confined to _gateway."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"
    written = _write_names(
        inbox, ["..dots_start.json", "middle..dots.json", "..json"], '{"bad": "json'
    )
    assert written

    valid_id = _drop_valid_command(env, "dot_test")
    env.service.poll_once()
    for name in written:
        _assert_moved_to_rejected(env, name, "malformed JSON")
    _assert_confined(env.root, valid_id)


def test_windows_reserved_filenames_do_not_crash(tmp_path: Path) -> None:
    """In plain words: Device names like CON and NUL must not crash or hang poll_once."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"
    written = _write_names(
        inbox, ["CON.json", "NUL.json", "AUX.json", "PRN.json", "COM1.json"], "invalid json"
    )

    valid_id = _drop_valid_command(env, "reserved_test")
    env.service.poll_once()
    for name in written:
        assert not (inbox / name).exists(), f"{name} stayed in inbox"
    _assert_confined(env.root, valid_id)


def test_long_and_unicode_filenames_do_not_crash(tmp_path: Path) -> None:
    """In plain words: Extreme filename lengths and unicode scripts are handled gracefully."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"
    names = [("a" * 200) + ".json", "команда_🚀_ñandú_測試.json"]
    written = _write_names(inbox, names, '{"id": "x"}')

    valid_id = _drop_valid_command(env, "long_unicode_test")
    env.service.poll_once()
    for name in written:
        assert not (inbox / name).exists(), f"{name} stayed in inbox"
    assert env.gateway.pending() != [] and len(env.gateway.pending()) == 1
    _assert_confined(env.root, valid_id)


BAD_IDS = [
    "../escaped_outbox",
    "..\\win_escaped",
    "col:on",
    "/absolute/leak",
    "a/b",
    "C:\\leak",
    "id with space",
    "tab\tid",
    "nul\x00byte",
]


def test_signed_command_id_path_traversal_is_rejected(tmp_path: Path) -> None:
    """In plain words: Validly signed ids with slashes or colons reach id handling, are refused."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"
    for index, bad_id in enumerate(BAD_IDS):
        cmd = signed(
            env,
            "propose",
            propose_args(env),
            actor="alice",
            roles=("engineer",),
            extra=SignOpts(cmd_id=bad_id),
        )
        assert cmd["id"] == bad_id
        (inbox / f"bad_id_{index}.json").write_text(json.dumps(cmd), encoding="utf-8")

    valid_id = _drop_valid_command(env, "id_traversal_test")
    env.service.poll_once()
    for index in range(len(BAD_IDS)):
        name = f"bad_id_{index}.json"
        _assert_moved_to_rejected(env, name, "id contains invalid characters")
    assert env.gateway.pending() != [] and len(env.gateway.pending()) == 1  # only the valid one
    assert len(env.plant.writes) == 0
    _assert_confined(env.root, valid_id)


@pytest.mark.parametrize("odd_id", ["..", ".", "CON", "NUL", "aux", "-", "_"])
def test_signed_ids_made_of_legal_characters_stay_inside_outbox(
    tmp_path: Path, odd_id: str
) -> None:
    """In plain words: Ids like '..' or 'CON' pass the character rule but cannot leave outbox/."""
    env = make_env(tmp_path)
    cmd = signed(
        env,
        "propose",
        propose_args(env),
        actor="alice",
        roles=("engineer",),
        extra=SignOpts(cmd_id=odd_id),
    )
    (env.root / "_gateway" / "inbox" / "odd.json").write_text(json.dumps(cmd), encoding="utf-8")
    env.service.poll_once()
    assert rejected_reason(env.root, "odd") is None
    produced = sorted(p.name for p in (env.root / "_gateway" / "outbox").iterdir())
    assert produced == [f"{odd_id}.json"]
    leaked = _unexpected_paths(env.root, env.root)
    assert not leaked, leaked


def test_overlong_signed_id_fails_closed_without_engine_change(tmp_path: Path) -> None:
    """In plain words: A 300-char id cannot be answered; the command must not stay applied."""
    env = make_env(tmp_path)
    long_id = "a" * 300
    cmd = signed(
        env,
        "propose",
        propose_args(env),
        actor="alice",
        roles=("engineer",),
        extra=SignOpts(cmd_id=long_id),
    )
    (env.root / "_gateway" / "inbox" / "long_id.json").write_text(
        json.dumps(cmd), encoding="utf-8"
    )
    env.service.poll_once()
    _assert_moved_to_rejected(env, "long_id.json")
    # Never stat a path built from the overlong id (ENAMETOOLONG on Python 3.12).
    produced = sorted(p.name for p in (env.root / "_gateway" / "outbox").iterdir())
    assert not [name for name in produced if name.startswith(long_id[:64])], produced
    leaked = _unexpected_paths(env.root, env.root)
    assert not leaked, leaked
    assert env.gateway.pending() == [], "command reported rejected but still applied"
    assert [e["reason_code"] for e in audit_events(env, "auth_reject")] == [
        "id contains invalid characters"
    ]


def test_failed_outbox_write_after_apply_is_audited_and_polling_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In plain words: An applied command whose answer cannot be written leaves an audit trail."""
    env = make_env(tmp_path)
    cmd_id = "applied_but_unanswered"
    cmd = signed(
        env,
        "propose",
        propose_args(env),
        actor="alice",
        roles=("engineer",),
        extra=SignOpts(cmd_id=cmd_id),
    )
    inbox = env.root / "_gateway" / "inbox"
    (inbox / "first.json").write_text(json.dumps(cmd), encoding="utf-8")

    def _boom(_cmd_id: str, _result: dict[str, Any]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(env.service, "_write_result", _boom)
    env.service.poll_once()
    monkeypatch.undo()

    assert len(env.gateway.pending()) == 1, "the command did take effect"
    assert outbox(env.root, cmd_id) is None
    failed = audit_events(env, "result_write_failed")
    assert [e["value"] for e in failed] == [cmd_id]
    assert not (inbox / "first.json").exists()
    assert audit_events(env, "service_error") == []
    valid_id = _drop_valid_command(env, "after_failure")
    env.service.poll_once()
    result = outbox(env.root, valid_id)
    assert result is not None and result["ok"] is True


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
    if not _create_junction_or_symlink(outside_dir, junc_path):
        pytest.skip("Operating system cannot create symlinks or junctions without elevation")

    valid_id = _drop_valid_command(env, "symlink_test")
    env.service.poll_once()

    assert secret_file.read_text(encoding="utf-8") == "critical_system_data"
    assert sorted(p.name for p in outside_dir.iterdir()) == ["secret.txt"]
    tolerated = (
        outside_dir,
        env.root / "_gateway" / "inbox" / "junc.json",
        env.root / "_gateway" / "rejected" / "junc.json",
    )
    _assert_confined(env.root, valid_id, base=tmp_path, tolerated=tolerated)


def test_two_files_with_same_id_in_same_poll(tmp_path: Path) -> None:
    """In plain words: A second validly signed file reusing an id is refused as replayed_id."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"
    shared_id = "duplicate_id_001"

    def sign_with_shared_id(value: float) -> dict[str, Any]:
        """Choose the id first, then sign (fresh nonce each time), so dedup is really tested."""
        return signed(
            env,
            "propose",
            propose_args(env, value),
            actor="alice",
            roles=("engineer",),
            extra=SignOpts(cmd_id=shared_id),
        )

    env_a, env_b = sign_with_shared_id(55.0), sign_with_shared_id(56.0)
    assert env_a["id"] == env_b["id"] == shared_id
    assert env_a["auth"]["nonce"] != env_b["auth"]["nonce"]
    assert env_a["sig"] != env_b["sig"]
    (inbox / "file_a.json").write_text(json.dumps(env_a), encoding="utf-8")
    (inbox / "file_b.json").write_text(json.dumps(env_b), encoding="utf-8")

    env.service.poll_once()

    assert rejected_reason(env.root, "file_a") is None
    assert rejected_reason(env.root, "file_b") == "replayed_id"
    _assert_moved_to_rejected(env, "file_b.json")
    out = outbox(env.root, shared_id)
    assert out is not None and out["ok"] is True
    assert [p.value for p in env.gateway.pending()] == [55.0], "second file must not apply"
    leaked = _unexpected_paths(env.root, env.root)
    assert not leaked, leaked


def test_file_growing_while_read_does_not_crash_poll(tmp_path: Path) -> None:
    """In plain words: Incomplete JSON written incrementally to inbox does not crash poll_once."""
    env = make_env(tmp_path)
    inbox = env.root / "_gateway" / "inbox"
    (inbox / "growing.json").write_text('{"id": "grow1", "cmd": "prop', encoding="utf-8")

    valid_id = _drop_valid_command(env, "growing_test")
    env.service.poll_once()

    _assert_moved_to_rejected(env, "growing.json", "malformed JSON")
    _assert_confined(env.root, valid_id)
