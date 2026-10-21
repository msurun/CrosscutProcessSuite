"""Tests for the dataset replay (ADR 010, S7): faults gate advice, debounce, mapping, log chain.

Data come from the simulated mill circuit (nominal, 3 h, 10 s samples). The fuzzy inputs are
patched to a constant 'low power, on-target P80' state so a healthy loop yields an advice at
every step; faults are injected into the mill_feed loop columns.
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import cache
from pathlib import Path

import numpy as np
import pytest
from crosscut_fuzzy.model import FuzzySystem, system_from_dict
from crosscut_loops.overview import LoopTags
from crosscut_sim.plants.mill_circuit import MillCircuitPlant
from crosscut_sim.scenarios import build_scenario
from crosscut_supervisor.audit import AuditLog
from crosscut_supervisor.config import GateRule, SupervisorConfig
from crosscut_supervisor.replay import (
    ReplayData,
    ReplayError,
    ReplaySettings,
    advise_series,
    replay_to_log,
)

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = system_from_dict(
    json.loads((ROOT / "fuzzy" / "examples" / "mill_feed_supervisor.json").read_text("utf-8"))
)
DURATION_S = 3 * 3600.0
SAMPLE_S = 10.0
WINDOW_S = 1800.0
FEED = "sim.mc.mill_feed"
GATE = GateRule("mill_feed", frozenset({"manual", "saturated", "flatline"}), frozenset())
CFG = SupervisorConfig(
    schema_version="1.0.0", id="mill", fuzzy_system_id="mill_feed_supervisor",
    output_id="feed_change", target_loop="mill_feed", mode="advisory", gates=(GATE,),
    silent_band=0.5, min_activation=0.2, min_interval_s=900.0, display_clamp=(-10.0, 10.0),
)
LOOP = LoopTags(
    name="mill_feed", pv=FEED, sp=FEED + "_sp", out=FEED + "_out", mode=FEED + "_mode",
    unit="t/h", eng_min=0.0, eng_max=300.0, delay_s=30.0, ultimate_period_s=600.0,
    out_low=0.0, out_high=100.0,
)
SETTINGS = ReplaySettings(window_s=WINDOW_S, step_s=300.0)
MANUAL = (4000.0, 7600.0)  # one hour of MAN
FLAT = (8400.0, 12000.0)  # one hour with PV and OUT frozen


@cache
def _clean_columns() -> dict[str, np.ndarray]:
    """Simulate the nominal mill circuit once; patch the fuzzy inputs to 'low power' (r5)."""
    plant = MillCircuitPlant()
    plant.reset(3, build_scenario("mill_circuit", "nominal", duration_s=DURATION_S))
    rows = []
    for second in range(int(DURATION_S)):
        if second % int(SAMPLE_S) == 0:
            rows.append([value for value, _ in plant.snapshot().values()])
        plant.step()
    table = np.array(rows)
    columns = {tag: table[:, i].copy() for i, tag in enumerate(plant.snapshot())}
    columns["sim.mc.mill_power"][:] = 2700.0
    columns["sim.mc.p80"][:] = 150.0
    return columns


def _data(columns: dict[str, np.ndarray] | None = None) -> ReplayData:
    """Replay data on the 10 s grid; a copy of the clean columns unless given."""
    cols = columns if columns is not None else {k: v.copy() for k, v in _clean_columns().items()}
    return ReplayData(np.arange(len(cols[FEED])) * SAMPLE_S, cols)


def _faulty() -> ReplayData:
    """Clean data with a MAN hour and a frozen PV/OUT hour in the mill_feed loop."""
    data = _data()
    t = data.t_s
    manual = (t >= MANUAL[0]) & (t < MANUAL[1])
    flat = (t >= FLAT[0]) & (t < FLAT[1])
    data.columns[FEED + "_mode"][manual] = 0.0
    for tag in (FEED, FEED + "_out"):
        data.columns[tag][flat] = data.columns[tag][flat][0]
    return data


def _run(data: ReplayData, config: SupervisorConfig = CFG) -> list:
    """Replay with the mill_feed loop and the default settings of this file."""
    return advise_series(SYSTEM, config, data, [LOOP], SETTINGS)


def _inside(advice, window: tuple[float, float]) -> bool:
    """True when the window of the advice lies completely inside the fault window."""
    end_s = advice.t_ns / 1e9
    return window[0] + WINDOW_S <= end_s <= window[1]


def test_no_advice_inside_injected_windows() -> None:
    """No non-hold advice once a full window lies in the MAN or the flatline period."""
    advices = _run(_faulty(), replace(CFG, min_interval_s=0.0))
    for advice in advices:
        if advice.gate.state != "blocked":
            assert not _inside(advice, MANUAL) and not _inside(advice, FLAT)
    assert any(a.gate.state != "blocked" for a in advices)


def test_blocked_records_name_the_fault() -> None:
    """Blocked records exist for both faults and name them; they are logged on transitions."""
    advices = _run(_faulty(), replace(CFG, min_interval_s=0.0))
    blocked = [a for a in advices if a.gate.state == "blocked"]
    assert all(a.direction == "hold" and a.magnitude is None for a in blocked)
    reasons = {reason for a in blocked for reason in a.gate.reasons}
    assert "manual:mill_feed" in reasons
    assert "flatline:mill_feed" in reasons
    steps_blocked = (MANUAL[1] - MANUAL[0] + FLAT[1] - FLAT[0]) / SETTINGS.step_s
    assert 0 < len(blocked) < steps_blocked / 2  # not one record per blocked step


def test_debounce_honours_min_interval() -> None:
    """Kept non-hold advices are at least min_interval_s apart; no debounce keeps more."""
    plain = [a for a in _run(_data(), replace(CFG, min_interval_s=0.0)) if a.direction != "hold"]
    kept = [a for a in _run(_data()) if a.direction != "hold"]
    times = [a.t_ns / 1e9 for a in kept]
    assert len(kept) < len(plain)
    assert all(b - a >= CFG.min_interval_s for a, b in zip(times, times[1:], strict=False))


def test_clean_run_gate_open_share(capsys: pytest.CaptureFixture[str]) -> None:
    """Without faults at least 90 % of the steps are not blocked (actual share is printed)."""
    advices = _run(_data(), replace(CFG, min_interval_s=0.0))
    steps = len(range(int(WINDOW_S), int(DURATION_S) + 1, int(SETTINGS.step_s)))
    open_steps = sum(1 for a in advices if a.gate.state == "open")
    with capsys.disabled():
        print(f"\nclean-run gate-open share: {open_steps}/{steps} = {open_steps / steps:.1%}")
    assert open_steps / steps >= 0.9


def test_ambiguous_variable_raises() -> None:
    """Two columns ending in '.p80' and no exact match: ReplayError names the variable."""
    columns = {k: v for k, v in _clean_columns().items() if k != "sim.mc.p80"}
    columns["a.p80"] = columns["sim.mc.mill_power"]
    columns["b.p80"] = columns["sim.mc.mill_power"]
    with pytest.raises(ReplayError, match="p80"):
        _run(_data(columns))


def test_unmapped_variable_raises() -> None:
    """No column for a variable gives a ReplayError naming it."""
    columns = {k: v for k, v in _clean_columns().items() if k != "sim.mc.mill_power"}
    with pytest.raises(ReplayError, match="mill_power"):
        _run(_data(columns))


def test_suffix_match_is_used_without_tag() -> None:
    """A variable without a tag matches the unique column ending in '.<id>'."""
    untagged = FuzzySystem(
        **{**SYSTEM.__dict__, "inputs": tuple(replace(v, tag=None) for v in SYSTEM.inputs)}
    )
    advices = advise_series(untagged, CFG, _data(), [LOOP], SETTINGS)
    assert advices


def test_replay_to_log_chain_verifies(tmp_path: Path) -> None:
    """The replayed advices are appended as a verifiable hash chain."""
    advices = _run(_faulty())
    log = AuditLog(tmp_path / "advice.jsonl")
    assert replay_to_log(advices, log) == len(advices) > 0
    report = log.verify()
    assert report.ok and report.records == len(advices)
