"""The readiness port built from the latest loop_kpi result in the runtime state."""

from __future__ import annotations

from pathlib import Path

from crosscut_runtime.controllers.wiring import make_readiness
from crosscut_runtime.store import RuntimeStore


def _state(root: Path, rows: dict[str, dict[str, object] | None]) -> None:
    jobs = {"k1": {"last_run_utc": "2026-01-01T00:00:00+00:00", "kpi": rows}}
    RuntimeStore(root).save_state({"jobs": jobs})


def test_missing_row_is_unknown_and_ready(tmp_path: Path) -> None:
    assert make_readiness(tmp_path)("L1") == {"ready": True, "reasons": ["readiness_unknown"]}
    _state(tmp_path, {"L1": None})
    assert make_readiness(tmp_path)("L1")["reasons"] == ["readiness_unknown"]


def test_saturated_and_manual_rows_are_not_ready(tmp_path: Path) -> None:
    _state(
        tmp_path,
        {
            "L1": {
                "saturation_fraction": 0.9,
                "service_factor": 1.0,
                "classification": "saturated",
            },
            "L2": {"saturation_fraction": 0.0, "service_factor": 0.1, "classification": "manual"},
            "L3": {
                "saturation_fraction": 0.0,
                "service_factor": 1.0,
                "classification": "ok",
                "flatline_fraction": 0.0,
                "stiction_advice": "unlikely",
            },
        },
    )
    port = make_readiness(tmp_path)
    assert port("L1") == {"ready": False, "reasons": ["saturated"]}
    assert port("L2") == {"ready": False, "reasons": ["manual"]}
    assert port("L3") == {"ready": True, "reasons": []}


def test_valve_and_frozen_pv_use_the_new_kpi_fields(tmp_path: Path) -> None:
    _state(tmp_path, {"L1": {"flatline_fraction": 0.9, "stiction_advice": "test_valve"}})
    assert make_readiness(tmp_path)("L1")["reasons"] == ["pv_frozen", "valve"]
