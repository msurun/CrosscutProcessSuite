"""Safe-start tests for the gateway entry point and the kill-latch fallback engine.

Pin that a set kill latch lets start-up continue without a policy file, that the HMAC key
file is refused when its permissions are insecure, that the fallback gateway has no targets
and stays off, and that self-approval compares actor names in normalized form.
Sources: the __main__, engine and keyfile modules as they exist; no src file is modified.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest
from crosscut_gateway import __main__ as cli
from crosscut_gateway import engine
from crosscut_gateway.actor import ActorContext
from crosscut_gateway.keyfile import default_key_path
from crosscut_gateway.policy import proposal_key
from test_engine_hardening import make
from test_gateway_scenarios import SimPlant, proposal


def _write_key(root: Path) -> Path:
    """Write a 32-byte HMAC key with owner-only permissions and return its path."""
    path = default_key_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"k" * 32)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path


def _args(root: Path, policy: Path, plant_map: Path) -> argparse.Namespace:
    """Build the parsed-argument namespace that _prepare reads."""
    return argparse.Namespace(root=root, policy=policy, plant_map=plant_map, roles=None)


def _set_kill_latch(root: Path) -> None:
    """Create the kill latch file inside the gateway directory of *root*."""
    gateway_dir = root / "_gateway"
    gateway_dir.mkdir(parents=True, exist_ok=True)
    (gateway_dir / "KILLED").write_text("", encoding="utf-8")


def test_prepare_accepts_missing_policy_when_kill_latch_is_set(tmp_path: Path) -> None:
    """With the kill latch set, a missing policy file does not block start-up."""
    _write_key(tmp_path)
    plant_map = tmp_path / "plant.json"
    plant_map.write_text("{}", encoding="utf-8")
    _set_kill_latch(tmp_path)
    inputs = cli._prepare(_args(tmp_path, tmp_path / "missing.json", plant_map))
    assert inputs is not None
    assert inputs.key == b"k" * 32


def test_prepare_refuses_missing_policy_without_kill_latch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without the kill latch, a missing policy file is still a start-up error."""
    _write_key(tmp_path)
    plant_map = tmp_path / "plant.json"
    plant_map.write_text("{}", encoding="utf-8")
    inputs = cli._prepare(_args(tmp_path, tmp_path / "missing.json", plant_map))
    assert inputs is None
    assert "policy file not found" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="key permissions are checked on POSIX only")
def test_load_key_refuses_insecure_key_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A key file readable by others is refused and the problem is reported."""
    path = _write_key(tmp_path)
    os.chmod(path, 0o644)
    assert cli._load_key(path) is None
    err = capsys.readouterr().err
    assert "gateway HMAC key file rejected" in err
    assert str(path) in err


def test_safe_gateway_has_no_targets_and_stays_off() -> None:
    """The fallback gateway tracks no targets and is in mode off."""
    gw = engine.safe_gateway(SimPlant())
    assert gw.status() == {}
    assert gw.mode == "off"


def test_self_approval_compares_normalized_names() -> None:
    """A proposal by ' Alice' cannot be approved by 'alice' (same person, normalized)."""
    gw = make("confirm", SimPlant())
    gw.tick(0)
    queued = proposal(55.0)
    proposer = ActorContext(actor=" Alice", roles=("operator",), session="s1")
    approver = ActorContext(actor="alice", roles=("operator",), session="s2")
    gw.propose(queued, actor_ctx=proposer)
    decision = gw.approve(proposal_key(queued), actor_ctx=approver)
    assert not decision.accepted
    assert decision.reason_code == "self_approval"
