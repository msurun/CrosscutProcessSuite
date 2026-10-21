"""Tests for the supervisor configuration loader and its cross-checks (ADR 010).

Systems come from the fuzzy example documents; documents are plain dicts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from crosscut_fuzzy.model import system_from_dict
from crosscut_supervisor.config import (
    GateRule,
    SupervisorConfigError,
    check_against_system,
    load_config,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "fuzzy" / "examples" / "mill_feed_supervisor.json"

VALID: dict[str, Any] = {
    "schema_version": "1.0.0",
    "id": "mill-feed",
    "fuzzy_system_id": "mill_feed_supervisor",
    "output_id": "feed_change",
    "target_loop": "FIC101",
    "mode": "advisory",
    "gates": [
        {"loop": "FIC101", "block_on": ["manual", "saturated"], "warn_on": ["oscillating"]},
        {"loop": "LIC201"},
    ],
    "silent_band": 0.5,
    "min_activation": 0.2,
    "min_interval_s": 60,
    "display_clamp": [-10, 10],
}


def _doc(**changes: Any) -> dict[str, Any]:
    """A copy of the valid document with fields replaced (None removes a field)."""
    doc = copy.deepcopy(VALID)
    for key, value in changes.items():
        if value is None:
            doc.pop(key)
        else:
            doc[key] = value
    return doc


def test_valid_config_loads() -> None:
    config = load_config(VALID)
    assert config.mode == "advisory"
    assert config.display_clamp == (-10.0, 10.0)
    assert config.gates[0] == GateRule(
        "FIC101", frozenset({"manual", "saturated"}), frozenset({"oscillating"})
    )
    assert config.gates[1].block_on == frozenset()
    assert config.fuzzy_version_id is None


def test_empty_gates_allowed() -> None:
    assert load_config(_doc(gates=[])).gates == ()


@pytest.mark.parametrize("mode", ["closed_loop", ""])
def test_mode_rejected(mode: str) -> None:
    with pytest.raises(SupervisorConfigError, match="mode"):
        load_config(_doc(mode=mode))


def test_missing_field_named() -> None:
    with pytest.raises(SupervisorConfigError, match="silent_band"):
        load_config(_doc(silent_band=None))


def test_unknown_field_named() -> None:
    with pytest.raises(SupervisorConfigError, match="write_path"):
        load_config({**VALID, "write_path": True})


def test_min_activation_out_of_range() -> None:
    with pytest.raises(SupervisorConfigError, match="min_activation"):
        load_config(_doc(min_activation=1.5))


def test_bad_gate_state_rejected() -> None:
    gates = [{"loop": "FIC101", "block_on": ["oscillating"]}]
    with pytest.raises(SupervisorConfigError, match="block_on"):
        load_config(_doc(gates=gates))


def test_clamp_order_and_length() -> None:
    with pytest.raises(SupervisorConfigError, match="display_clamp"):
        load_config(_doc(display_clamp=[5, 5]))
    with pytest.raises(SupervisorConfigError, match="display_clamp"):
        load_config(_doc(display_clamp=[1, 2, 3]))


def test_duplicate_gate_loops_rejected() -> None:
    gates = [{"loop": "FIC101"}, {"loop": "FIC101"}]
    with pytest.raises(SupervisorConfigError, match="unique"):
        load_config(_doc(gates=gates))


def test_target_loop_must_be_gated() -> None:
    with pytest.raises(SupervisorConfigError, match="target_loop"):
        load_config(_doc(target_loop="OTHER"))


def test_check_against_system_ok_and_unknown() -> None:
    system = system_from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    check_against_system(load_config(VALID), system)
    with pytest.raises(SupervisorConfigError, match="output_id"):
        check_against_system(load_config(_doc(output_id="nope")), system)


def test_bundled_mill_feed_advisor_example_is_valid() -> None:
    """The example the web UI offers loads, targets the mill circuit and fits its fuzzy system."""
    example = Path(__file__).resolve().parents[1] / "examples" / "mill_feed_advisor.json"
    config = load_config(json.loads(example.read_text(encoding="utf-8")))
    system_path = EXAMPLE.with_name(f"{config.fuzzy_system_id}.json")
    system = system_from_dict(json.loads(system_path.read_text(encoding="utf-8")))
    check_against_system(config, system)
    assert config.target_loop == "mill_feed" and config.mode == "advisory"
