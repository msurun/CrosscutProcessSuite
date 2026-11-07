"""Tests for the switchable KILL file trigger: ``--no-kill-file`` and the site config key.

The flag wins over ``<root>/_auth/config.json``; without either the trigger stays on.
The service ignores the KILL file when it was started with ``allow_kill_file=False``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from auth_helpers import AuthEnv, make_env
from crosscut_gateway import __main__ as cli
from crosscut_gateway import engine
from crosscut_gateway import service as gateway_service
from test_gateway_scenarios import POLICY, TAG, SimPlant


def _args(root: Path, *flags: str) -> object:
    """Parse the gateway arguments with ``root`` and extra flags."""
    return cli.parse_args(["--root", str(root), "--policy", "p", "--plant-map", "m", *flags])


def _write_config(root: Path, text: str) -> None:
    """Write ``<root>/_auth/config.json`` with ``text``."""
    path = root / "_auth" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")


def test_default_allows_kill_file(tmp_path: Path) -> None:
    """No flag and no config file: the KILL file trigger is on."""
    assert cli.kill_file_allowed(_args(tmp_path)) is True  # type: ignore[arg-type]


def test_no_kill_file_flag_turns_it_off(tmp_path: Path) -> None:
    """--no-kill-file disables the trigger."""
    assert cli.kill_file_allowed(_args(tmp_path, "--no-kill-file")) is False  # type: ignore[arg-type]


def test_config_file_can_turn_it_off_and_flag_overrides(tmp_path: Path) -> None:
    """kill_file_enabled=false switches it off; --allow-kill-file switches it back on."""
    _write_config(tmp_path, json.dumps({"kill_file_enabled": False}))
    assert cli.kill_file_allowed(_args(tmp_path)) is False  # type: ignore[arg-type]
    assert cli.kill_file_allowed(_args(tmp_path, "--allow-kill-file")) is True  # type: ignore[arg-type]


def test_unreadable_config_keeps_kill_file_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A broken config file never removes a way to stop the gateway."""
    _write_config(tmp_path, "{not json")
    assert cli.kill_file_allowed(_args(tmp_path)) is True  # type: ignore[arg-type]
    assert "KILL file stays enabled" in capsys.readouterr().err


def test_service_ignores_kill_file_when_disabled(tmp_path: Path) -> None:
    """With allow_kill_file=False the KILL file is left alone and the gateway keeps running."""
    env: AuthEnv = make_env(tmp_path, start_floor=False)
    gateway = engine.WriteGateway(SimPlant(), {TAG: POLICY}, "confirm")
    options = gateway_service.ServiceOptions(
        auth_required=True, key_path=env.key_path, allow_kill_file=False, enforce_start_floor=False
    )
    service = gateway_service.GatewayService(tmp_path, gateway, clock=env.clock, options=options)
    kill = tmp_path / "_gateway" / "KILL"
    kill.write_text("", encoding="utf-8")
    service.poll_once()
    assert kill.exists()
    assert gateway.killed is False
