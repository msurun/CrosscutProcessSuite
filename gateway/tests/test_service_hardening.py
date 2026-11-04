"""Hardening tests for the inbox service: malformed input, vanishing files and the serve loop.

Written before the implementation; they describe how poll_once, serve and record_service_error
must behave when inbox files are broken, disappear, or when a cycle raises.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, cast

import pytest
from auth_helpers import (
    AuthEnv,
    drop,
    make_env,
    outbox,
    propose_args,
    rejected_reason,
    signed,
)
from crosscut_gateway import service as gateway_service


class _FlakyService:
    """Stub service whose poll_once fails on the first call and stops the loop on the third."""

    def __init__(self, stop_event: threading.Event) -> None:
        """Remember the stop event and start with zero cycles and no recorded errors."""
        self.stop_event = stop_event
        self.calls = 0
        self.errors: list[str] = []

    def poll_once(self) -> None:
        """Raise on the first cycle, then count cycles and set the stop event on the third."""
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        if self.calls >= 3:
            self.stop_event.set()

    def record_service_error(self, exc: BaseException) -> None:
        """Remember the class name of each error the loop reports."""
        self.errors.append(type(exc).__name__)


class _InterruptingService:
    """Stub service whose poll_once stops the loop and then raises KeyboardInterrupt."""

    def __init__(self, stop_event: threading.Event) -> None:
        """Remember the stop event so a swallowed interrupt cannot hang the test."""
        self.stop_event = stop_event

    def poll_once(self) -> None:
        """Set the stop event, then raise KeyboardInterrupt."""
        self.stop_event.set()
        raise KeyboardInterrupt

    def record_service_error(self, exc: BaseException) -> None:
        """Accept reported errors; this stub should never receive one."""


def _inbox(env: AuthEnv) -> Path:
    """Return the inbox directory of the test environment."""
    return env.root / "_gateway" / "inbox"


def _rejected(env: AuthEnv) -> Path:
    """Return the rejected directory of the test environment."""
    return env.root / "_gateway" / "rejected"


def _assert_rejected_and_polling_continues(env: AuthEnv, name: str) -> None:
    """Check that a broken inbox file was moved to rejected and a valid command still ran."""
    assert not (_inbox(env) / name).exists()
    assert (_rejected(env) / name).exists()
    assert (_rejected(env) / (name + ".reason.txt")).exists()
    assert (env.root / "_gateway" / "state.json").exists()


def test_invalid_utf8_file_is_rejected_and_polling_continues(tmp_path: Path) -> None:
    """A non-UTF-8 inbox file is rejected while a valid command in the same cycle still runs."""
    env = make_env(tmp_path)
    _inbox(env).mkdir(parents=True, exist_ok=True)
    (_inbox(env) / "bad.json").write_bytes(b"\xff")
    envelope = signed(env, "propose", propose_args(env), roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    _assert_rejected_and_polling_continues(env, "bad.json")
    assert outbox(env.root, envelope["id"])["ok"] is True


def test_deeply_nested_json_is_rejected(tmp_path: Path) -> None:
    """A deeply nested JSON document is rejected without raising out of poll_once."""
    env = make_env(tmp_path)
    _inbox(env).mkdir(parents=True, exist_ok=True)
    (_inbox(env) / "deep.json").write_text("[" * 100000, encoding="utf-8")
    env.service.poll_once()
    _assert_rejected_and_polling_continues(env, "deep.json")


def test_signed_propose_with_huge_int_value_is_rejected(tmp_path: Path) -> None:
    """A signed propose whose value is out of range is rejected and nothing is written."""
    env = make_env(tmp_path)
    args = propose_args(env)
    args["value"] = 10**400
    envelope = signed(env, "propose", args, roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    reason = rejected_reason(env.root, envelope["id"])
    assert reason is not None
    assert "out of range" in reason or outbox(env.root, envelope["id"])["ok"] is False
    assert not env.gateway.pending()


def test_directory_named_json_is_moved_away(tmp_path: Path) -> None:
    """A directory named like a command is moved out of the inbox and later commands still run."""
    env = make_env(tmp_path)
    (_inbox(env) / "x.json").mkdir(parents=True)
    envelope = signed(env, "propose", propose_args(env), roles=("engineer",))
    drop(env, envelope)
    env.service.poll_once()
    assert not (_inbox(env) / "x.json").is_dir()
    assert outbox(env.root, envelope["id"])["ok"] is True


def test_vanishing_file_is_skipped_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that disappears between listing and reading is skipped without a service_error."""
    env = make_env(tmp_path)
    _inbox(env).mkdir(parents=True, exist_ok=True)
    (_inbox(env) / "v.json").write_text("{}", encoding="utf-8")

    def _vanish(self: gateway_service.GatewayService, filepath: Path) -> None:
        """Delete the file under the service's feet, then report it missing."""
        filepath.unlink()
        raise FileNotFoundError(filepath)

    monkeypatch.setattr(gateway_service.GatewayService, "_read_command", _vanish)
    env.service.poll_once()
    events = [record["event"] for record in env.gateway.audit_records()]
    assert "service_error" not in events


def test_serve_survives_a_failing_cycle() -> None:
    """serve keeps looping after a RuntimeError, reports its class name, and returns on stop."""
    stop_event = threading.Event()
    stub = _FlakyService(stop_event)
    gateway_service.serve(cast(Any, stub), 0.001, stop_event)
    assert stub.calls >= 3
    assert stub.errors == ["RuntimeError"]


def test_serve_lets_keyboard_interrupt_through() -> None:
    """serve does not swallow KeyboardInterrupt raised by a cycle."""
    stop_event = threading.Event()
    stub = _InterruptingService(stop_event)
    with pytest.raises(KeyboardInterrupt):
        gateway_service.serve(cast(Any, stub), 0.001, stop_event)


def test_service_error_is_audited_with_class_name_only(tmp_path: Path) -> None:
    """A reported service error is audited with its class name and without its message."""
    env = make_env(tmp_path)
    cast(Any, env.service).record_service_error(RuntimeError("secret detail"))
    records = env.gateway.audit_records()
    assert records[-1]["event"] == "service_error"
    assert records[-1]["reason_code"] == "RuntimeError"
    assert "secret detail" not in str(records)
