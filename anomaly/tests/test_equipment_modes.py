"""Tests for equipment anomaly models per operating mode (#146)."""

import numpy as np
from crosscut_anomaly.equipment_learning import (
    ALL_RUNNING_LIMITS,
    MODE_LIMITS,
    EquipmentModel,
    learn_equipment,
    training_mask,
)

N = 1200


def _pump() -> tuple:
    """Pump with two modes (normal, high) of 500 samples each and 200 stopped samples."""
    rng = np.random.default_rng(146)
    times = np.arange(N, dtype=float)
    labels = np.array(["normal"] * 500 + ["stopped"] * 200 + ["high"] * 500, dtype=object)
    out = np.where(labels == "high", 80.0, 50.0) + 5 * np.sin(times / 25)
    data = {"PV": out + rng.normal(0, 0.1, N), "SP": out, "OUT": out, "MODE": np.ones(N),
            "CURRENT": 2 * out + rng.normal(0, 0.2, N)}
    equipment = {"id": "pump", "loops": ["flow"],
                 "signals": [{"tag": "CURRENT", "kind": "current"}]}
    loops = [{"id": "flow", "pv": "PV", "sp": "SP", "out": "OUT", "mode": "MODE"}]
    return times, data, equipment, loops, labels


def test_stopped_mode_samples_are_excluded_from_training() -> None:
    """Samples labelled stopped count as stopped even without a running signal."""
    times, data, equipment, loops, labels = _pump()
    _, reasons = training_mask(times, data, equipment, loops, labels)
    assert reasons["stopped"] == 200


def test_per_mode_models_and_fallback_flag() -> None:
    """Modes with enough data get their own model; a thin mode is flagged all_running."""
    times, data, equipment, loops, labels = _pump()
    labels = labels.copy()
    labels[500:520] = "start_up"  # 20 samples: too few for a model of its own
    model = learn_equipment(times, data, equipment, loops, labels=labels)
    assert set(model.by_mode) == {"normal", "high"}
    assert model.mode_limits == {"normal": MODE_LIMITS, "high": MODE_LIMITS,
                                 "start_up": ALL_RUNNING_LIMITS}
    active, flag = model.for_mode("high")
    assert flag == MODE_LIMITS and active is model.by_mode["high"]
    assert model.for_mode("start_up") == (model, ALL_RUNNING_LIMITS)
    assert model.for_mode(None)[1] == ALL_RUNNING_LIMITS


def test_mode_models_round_trip() -> None:
    """Per-mode regressions are learned on their own samples and survive persistence."""
    times, data, equipment, loops, labels = _pump()
    model = learn_equipment(times, data, equipment, loops, labels=labels)
    restored = EquipmentModel.from_dict(model.to_dict())
    assert set(restored.by_mode) == {"normal", "high"}
    assert restored.mode_limits == model.mode_limits
    high = restored.by_mode["high"].regressions["CURRENT"]
    assert high["residual_std"] > 0 and high["outputs"] == ["OUT"]


def test_without_labels_nothing_changes() -> None:
    """Learning without labels has no per-mode models (backwards compatible)."""
    times, data, equipment, loops, _ = _pump()
    model = learn_equipment(times, data, equipment, loops)
    assert model.by_mode == {} and model.mode_limits == {}
