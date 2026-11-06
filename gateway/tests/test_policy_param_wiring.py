"""Start-up, reload and CLI wiring of the PID parameter targets (ADR 014).

A parameter target in the policy and a pid_param target in the plant map must match exactly;
any mismatch refuses start-up (exit code 2) or reload and changes nothing.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from auth_helpers import KEY
from crosscut_gateway import __main__ as cli
from crosscut_gateway import engine, policy_pin
from crosscut_gateway.engine_params import ParamConfig
from crosscut_gateway.engine_wiring import check_param_wiring
from crosscut_gateway.interfaces import ParamPolicy
from crosscut_gateway.keyfile import default_key_path
from crosscut_gateway.opcua_plant import OpcUaPlant
from crosscut_gateway.policy import PolicyError
from test_engine_params import KP, PARAMS, TD, TI, ParamPlant, events, it, make, queued
from test_gateway_scenarios import POLICY, TAG, SimPlant
from test_param_wiring import policy_document

SP_ENTRY: dict[str, Any] = {
    "setpoint_node": "ns=2;s=SP", "readback_node": "ns=2;s=SP", "mode_node": "ns=2;s=M",
    "source_node": "ns=2;s=SRC", "remote_value": 1, "local_value": 0, "release_value": 0,
    "mode_values": {"CAS": 2},
}
PARAM_ENTRY: dict[str, Any] = {
    "param_node": "ns=2;s=KP", "data_type": "Double", "mode_node": "ns=2;s=M",
    "mode_values": {"CAS": 2},
}
HEARTBEAT = {"node": "ns=2;s=HB", "period_s": 1.0}


def plant_map(*, param_tags: tuple[str, ...], setpoint_tags: tuple[str, ...] = (TAG,)) -> dict:
    """A plant map with the given setpoint and pid_param tags (nothing connects to it)."""
    targets = {tag: dict(SP_ENTRY) for tag in setpoint_tags}
    targets.update({tag: dict(PARAM_ENTRY) for tag in param_tags})
    return {
        "version": 1, "endpoint": "opc.tcp://127.0.0.1:1", "heartbeat": HEARTBEAT,
        "targets": targets,
    }


@pytest.fixture
def make_plant() -> Iterator[Any]:
    """Factory of OpcUaPlant objects that are closed at teardown."""
    plants: list[OpcUaPlant] = []

    def factory(data: dict) -> OpcUaPlant:
        plant = OpcUaPlant(data)
        plants.append(plant)
        return plant

    yield factory
    for plant in plants:
        plant.close()


def pinned(tmp_path: Path, document: dict[str, Any]) -> Path:
    """Write ``document`` as the policy file with a valid pin."""
    path = tmp_path / "policy" / "write-policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    signers = policy_pin.PinSigners("author1", "approver1")
    policy_pin.create_pin(path, KEY, signers, now=datetime(2026, 1, 1, tzinfo=UTC))
    return path


def start(path: Path, plant: Any) -> engine.WriteGateway:
    """Start from the pinned policy file in confirm mode."""
    return engine.start_from_policy_file(path, plant, "confirm", key=KEY)


def param_plant(tag: str) -> ParamPlant:
    """A fake plant that also holds the parameter ``tag``."""
    plant = ParamPlant()
    plant.params[tag] = 2.5
    return plant


def test_start_carries_the_parameter_targets_to_the_engine(tmp_path: Path) -> None:
    gateway = start(pinned(tmp_path, policy_document()), param_plant("FIC101.KP"))
    assert gateway.target_state("FIC101.KP") == "enabled"
    assert gateway.target_state(TAG) == "enabled"


def test_start_refuses_param_targets_for_a_plant_without_param_methods(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="cannot read or write parameters"):
        start(pinned(tmp_path, policy_document()), SimPlant())


def test_start_refuses_param_target_missing_from_the_plant_map(
    tmp_path: Path, make_plant: Any
) -> None:
    plant = make_plant(plant_map(param_tags=()))
    with pytest.raises(PolicyError, match="'FIC101.KP' is not a pid_param target"):
        start(pinned(tmp_path, policy_document()), plant)


def test_start_refuses_plant_map_param_target_without_policy(
    tmp_path: Path, make_plant: Any
) -> None:
    document = policy_document()
    del document["targets"]["FIC101.KP"]
    plant = make_plant(plant_map(param_tags=("FIC101.KP",)))
    with pytest.raises(PolicyError, match="has no pid_param policy"):
        start(pinned(tmp_path, document), plant)


def test_start_refuses_a_tag_that_is_setpoint_in_policy_and_param_in_the_map(
    tmp_path: Path, make_plant: Any
) -> None:
    document = policy_document()
    document["targets"]["FIC101.KP"] = dict(document["targets"][TAG])
    plant = make_plant(plant_map(param_tags=("FIC101.KP",)))
    with pytest.raises(PolicyError, match="a setpoint target of the policy"):
        start(pinned(tmp_path, document), plant)


def test_start_accepts_matching_policy_and_plant_map(tmp_path: Path, make_plant: Any) -> None:
    plant = make_plant(plant_map(param_tags=("FIC101.KP",)))
    gateway = start(pinned(tmp_path, policy_document()), plant)
    assert gateway.target_state("FIC101.KP") == "enabled"


def test_setpoint_only_policy_and_map_still_start(tmp_path: Path, make_plant: Any) -> None:
    document = policy_document()
    del document["targets"]["FIC101.KP"]
    gateway = start(pinned(tmp_path, document), make_plant(plant_map(param_tags=())))
    assert gateway.target_state(TAG) == "enabled"


def test_overlapping_tag_is_refused_by_the_check_itself() -> None:
    with pytest.raises(PolicyError, match="both a setpoint and a parameter"):
        check_param_wiring(ParamPlant(), {KP}, {KP})


def test_main_exits_with_2_and_names_the_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key_path = default_key_path(tmp_path)
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(KEY)
    if os.name == "posix":
        os.chmod(key_path, 0o600)
    policy = pinned(tmp_path, policy_document())
    map_path = tmp_path / "plant-map.json"
    map_path.write_text(json.dumps(plant_map(param_tags=())), encoding="utf-8")
    code = cli.main(["--root", str(tmp_path), "--policy", str(policy),
                     "--plant-map", str(map_path)])
    assert code == 2
    assert "pid_param" in capsys.readouterr().err


def new_params() -> dict[str, ParamPolicy]:
    """A parameter set that drops FIC101.TI and tightens the gain limits."""
    tighter = ParamPolicy(**{**PARAMS[KP].__dict__, "limits": (0.5, 5.0)})
    return {KP: tighter, TD: PARAMS[TD]}


def test_swap_replaces_both_kinds_and_drops_queued_sets_with_audit() -> None:
    gateway, _ = make("confirm")
    key = queued(gateway, it(KP, 3.0))
    gateway.set_mode("advisory")
    params = {KP: new_params()[KP]}
    gateway.swap_policies({TAG: POLICY}, "confirm", digest="d1", params=params)
    assert gateway.pending_params() == []
    flushed = events(gateway, "param_flushed")
    assert flushed and flushed[-1]["reason_code"] == "policy_reload" and flushed[-1]["key"] == key
    assert gateway.target_state(TI) is None and gateway.target_state(KP) == "enabled"


def test_refused_swap_changes_nothing() -> None:
    gateway, _ = make("confirm")
    queued(gateway, it(KP, 3.0))
    gateway.set_mode("advisory")
    before = gateway.status()
    with pytest.raises(ValueError, match="both a setpoint and a parameter"):
        gateway.swap_policies({TAG: POLICY, KP: POLICY}, "confirm", params=dict(PARAMS))
    assert gateway.status() == before and len(gateway.pending_params()) == 1


def test_swap_with_param_targets_is_refused_for_a_plant_without_param_methods() -> None:
    gateway = engine.WriteGateway(SimPlant(), {TAG: POLICY}, "advisory")
    with pytest.raises(ValueError, match="cannot read or write parameters"):
        gateway.swap_policies({TAG: POLICY}, "confirm", params={KP: PARAMS[KP]})
    assert gateway.status() == {TAG: "enabled"}


def test_swap_without_params_keeps_the_current_parameter_targets() -> None:
    gateway = engine.WriteGateway(
        ParamPlant(), {TAG: POLICY}, "advisory", params=ParamConfig(dict(PARAMS))  # type: ignore[arg-type]
    )
    gateway.swap_policies({TAG: POLICY}, "confirm")
    assert gateway.target_state(KP) == "enabled"
