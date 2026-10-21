"""Table-driven tests for the supervisor gates (ADR 010, step S4).

Rows use exactly the module 1 keys; one test builds a real row with the loops package.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pytest
from crosscut_loops.overview import LoopTags, analyze_dataset
from crosscut_supervisor.config import GateRule, SupervisorConfig
from crosscut_supervisor.gates import GateResult, gate_inputs_ok, gate_state

BASE = SupervisorConfig(
    schema_version="1.0.0", id="s", fuzzy_system_id="f", output_id="o", target_loop="L1",
    mode="advisory", gates=(), silent_band=0.1, min_activation=0.1, min_interval_s=60.0,
    display_clamp=(-1.0, 1.0),
)
FULL = GateRule(
    "L1", frozenset({"manual", "saturated", "flatline", "unknown"}), frozenset({"oscillating"})
)


def _cfg(*rules: GateRule) -> SupervisorConfig:
    """A config with the given gate rules."""
    return replace(BASE, gates=rules)


def _row(name: str = "L1", **over: Any) -> dict[str, Any]:
    """A healthy hand-built row with the real module 1 keys, overridden by ``over``."""
    row: dict[str, Any] = {
        "name": name, "status": "ok", "classification": "normal", "findings": [],
        "service_percent": 100, "health_percent": 90, "not_assessed": [],
    }
    row.update(over)
    return row


CASES = [
    ("healthy", [_row()], _cfg(FULL), "open", ()),
    ("missing row", [_row("OTHER")], _cfg(FULL), "blocked", ("loop_missing:L1",)),
    ("no rows", [], _cfg(FULL), "blocked", ("loop_missing:L1",)),
    ("not_assessed blocks with unknown", [_row(status="not_assessed")], _cfg(FULL),
     "blocked", ("not_assessed:L1",)),
    ("not_assessed degrades without unknown", [_row(status="not_assessed")],
     _cfg(GateRule("L1", frozenset({"manual"}), frozenset())), "degraded", ("not_assessed:L1",)),
    ("manual by classification", [_row(classification="manual")], _cfg(FULL),
     "blocked", ("manual:L1",)),
    ("manual by service 49", [_row(service_percent=49)], _cfg(FULL), "blocked", ("manual:L1",)),
    ("service 50 is not manual", [_row(service_percent=50)], _cfg(FULL), "open", ()),
    ("manual not in block_on", [_row(classification="manual")],
     _cfg(GateRule("L1", frozenset({"flatline"}), frozenset())), "open", ()),
    ("saturated by classification", [_row(classification="saturated")], _cfg(FULL),
     "blocked", ("saturated:L1",)),
    ("saturated by finding", [_row(findings=[{"code": "saturated", "params": {}}])], _cfg(FULL),
     "blocked", ("saturated:L1",)),
    ("flatline finding", [_row(findings=[{"code": "flatline", "params": {}}])], _cfg(FULL),
     "blocked", ("flatline:L1",)),
    ("oscillating warns", [_row(classification="oscillating")], _cfg(FULL),
     "degraded", ("oscillating:L1",)),
    ("oscillating finding warns", [_row(findings=[{"code": "oscillating", "params": {}}])],
     _cfg(FULL), "degraded", ("oscillating:L1",)),
    ("oscillating not in warn_on", [_row(classification="oscillating")],
     _cfg(GateRule("L1", frozenset({"manual"}), frozenset())), "open", ()),
    ("health None alone", [_row(health_percent=None)], _cfg(FULL), "open", ()),
    ("no rules", [_row(classification="manual")], _cfg(), "open", ()),
    ("multi reasons sorted unique",
     [_row(classification="saturated", findings=[{"code": "flatline", "params": {}}]),
      _row("L2", classification="oscillating")],
     _cfg(FULL, GateRule("L2", frozenset(), frozenset({"oscillating"}))),
     "blocked", ("flatline:L1", "oscillating:L2", "saturated:L1")),
    ("second rule missing", [_row()], _cfg(FULL, GateRule("L2", frozenset(), frozenset())),
     "blocked", ("loop_missing:L2",)),
]


@pytest.mark.parametrize(("label", "rows", "config", "state", "reasons"), CASES,
                         ids=[case[0] for case in CASES])
def test_gate_state(label: str, rows: list, config: SupervisorConfig, state: str,
                    reasons: tuple[str, ...]) -> None:
    """Each branch of the gate logic gives the documented state and reasons."""
    assert gate_state(rows, config) == GateResult(state, reasons)  # type: ignore[arg-type]


def test_real_module1_row_keys_match() -> None:
    """A row produced by the real loops package is read correctly (a stuck OUT is saturated)."""
    count = 4000
    columns = {
        "PV": np.linspace(40.0, 45.0, count), "SP": np.full(count, 50.0),
        "OUT": np.full(count, 100.0), "MODE": np.ones(count),
    }
    tags = LoopTags(name="L1", pv="PV", sp="SP", out="OUT", mode="MODE", unit="degC",
                    eng_min=0.0, eng_max=100.0, delay_s=30.0, ultimate_period_s=600.0,
                    out_low=0.0, out_high=100.0)
    rows = analyze_dataset(np.arange(count, dtype=float), columns, [tags])
    result = gate_state(rows, _cfg(FULL))
    assert result.state == "blocked"
    assert "saturated:L1" in result.reasons


INPUT_CASES = [
    ("fine", {"a": 1.0}, {"a": (0.0, 2.0)}, []),
    ("edges inclusive", {"a": 0.0, "b": 2.0}, {"a": (0.0, 2.0), "b": (0.0, 2.0)}, []),
    ("nan", {"a": float("nan")}, {"a": (0.0, 2.0)}, ["input_nan:a"]),
    ("none", {"a": None}, {"a": (0.0, 2.0)}, ["input_missing:a"]),
    ("missing", {}, {"a": (0.0, 2.0)}, ["input_missing:a"]),
    ("low", {"a": -0.1}, {"a": (0.0, 2.0)}, ["input_out_of_range:a"]),
    ("high", {"a": 2.1}, {"a": (0.0, 2.0)}, ["input_out_of_range:a"]),
    ("extra input ignored", {"a": 1.0, "z": 9e9}, {"a": (0.0, 2.0)}, []),
    ("several sorted", {"b": float("nan")}, {"b": (0.0, 1.0), "a": (0.0, 1.0)},
     ["input_missing:a", "input_nan:b"]),
]


@pytest.mark.parametrize(("label", "snapshot", "ranges", "expected"), INPUT_CASES,
                         ids=[case[0] for case in INPUT_CASES])
def test_gate_inputs_ok(label: str, snapshot: dict, ranges: dict, expected: list[str]) -> None:
    """NaN, None, missing and out-of-range inputs each give their own reason."""
    assert gate_inputs_ok(snapshot, ranges) == expected
