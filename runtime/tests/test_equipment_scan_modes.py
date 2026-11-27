"""Verify equipment scanning uses limits per operating mode and skips stopped mode (#146)."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from crosscut_anomaly.equipment_learning import learn_equipment
from crosscut_connectors import mode_eval
from crosscut_connectors.base import LiveValue
from crosscut_runtime.jobs import equipment_scan

N = 1100
MODES = [
    {"id": "stopped", "condition": {"clauses": [{"tag": "SPEED", "op": "<", "value": 1}]}},
    {"id": "high", "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 150}]}},
    {"id": "normal", "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 50}]}},
]
EQUIPMENT = {"id": "pump", "loops": ["flow"], "signals": [{"tag": "CURRENT", "kind": "current"}]}
LOOPS = [{"id": "flow", "pv": "PV", "sp": "SP", "out": "OUT", "mode": "MODE"}]
SITE = {"equipment": [EQUIPMENT], "loops": LOOPS, "modes": MODES}


def _job(tmp_path: Path, values: dict[str, float]) -> equipment_scan.EquipmentScanJob:
    """Learn a two-mode pump (current = 2*OUT in normal, 3*OUT in high) and wrap a scanner."""
    rng = np.random.default_rng(147)
    times = np.arange(N, dtype=float)
    feed = np.array([100.0] * 550 + [200.0] * 550)
    out = np.where(feed > 150, 80.0, 50.0) + 5 * np.sin(times / 25)
    factor = np.where(feed > 150, 3.0, 2.0)
    data = {"PV": out + rng.normal(0, 0.1, N), "SP": out, "OUT": out, "MODE": np.ones(N),
            "CURRENT": factor * out + rng.normal(0, 0.2, N), "FEED": feed, "SPEED": np.full(N, 5.0)}
    labels = mode_eval.evaluate(SITE, "pump", data, N)
    model = learn_equipment(times, data, EQUIPMENT, LOOPS, labels=labels)
    folder = tmp_path / "_anomaly" / "equipment"
    folder.mkdir(parents=True)
    (folder / "pump.model.json").write_text(json.dumps(model.to_dict()))
    connector = SimpleNamespace(read_live=lambda tags: {
        tag: LiveValue(values[tag], 0, "2026-01-01T00:00:00Z") for tag in tags})
    job = equipment_scan.EquipmentScanJob({"equipment": ["pump"], "period_s": 1, "persistence": 1},
                                          SITE, connector, tmp_path)
    job.clock = lambda: 1767225600.0
    return job


def _values(feed: float, speed: float, current_factor: float) -> dict[str, float]:
    out = 80.0 if feed > 150 else 50.0
    return {"PV": out, "SP": out, "OUT": out, "MODE": 1.0, "CURRENT": current_factor * out,
            "FEED": feed, "SPEED": speed}


def test_limits_follow_the_current_mode(tmp_path: Path) -> None:
    """The same current is normal in high mode (factor 3) and abnormal in normal mode."""
    values = _values(200.0, 5.0, 3.0)
    job = _job(tmp_path, values)
    state = job.run()["equipment"]["pump"]
    assert state["mode"] == "high" and state["limits"] == "mode" and state["status"] == "ok"
    values.update(_values(100.0, 5.0, 3.0))  # normal mode, but the high-mode current
    result = job.run()["equipment"]["pump"]
    assert result["mode"] == "normal" and result["limits"] == "mode"
    assert result["status"] == "anomaly"


def test_unknown_mode_falls_back_to_all_running_with_flag(tmp_path: Path) -> None:
    """Missing mode inputs give the all-running model and say so."""
    values = _values(200.0, 5.0, 3.0)
    job = _job(tmp_path, values)
    del values["FEED"]
    job.connector.read_live = lambda tags: {
        tag: LiveValue(values[tag], 0, "2026-01-01T00:00:00Z") for tag in tags if tag in values}
    result = job.run()["equipment"]["pump"]
    assert result["mode"] == "unknown" and result["limits"] == "all_running"


def test_stopped_mode_is_not_scored(tmp_path: Path) -> None:
    """Mode stopped suppresses scoring even with a wild current."""
    values = _values(200.0, 0.0, 30.0)
    job = _job(tmp_path, values)
    assert job.run()["equipment"]["pump"]["status"] == "stopped"
    assert not job.events_path.exists()
