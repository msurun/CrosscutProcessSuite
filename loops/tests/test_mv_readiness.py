"""Tests of mv_readiness.loop_readiness: each reason alone, the ready case, unknown fields."""

from __future__ import annotations

import pytest
from crosscut_loops.mv_readiness import loop_readiness

GOOD = {
    "service_factor": 1.0,
    "saturation_fraction": 0.0,
    "flatline_fraction": 0.0,
    "classification": "ok",
}


def with_(**changes: object) -> dict:
    """The healthy KPI row with some fields changed."""
    return {**GOOD, **changes}


def test_healthy_loop_is_ready() -> None:
    """A loop in AUTO, off its limits, with a moving PV is ready with no reasons."""
    assert loop_readiness(GOOD) == {"ready": True, "reasons": []}


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"saturation_fraction": 0.5}, "saturated"),
        ({"flatline_fraction": 0.9}, "pv_frozen"),
        ({"service_factor": 0.1}, "manual"),
        ({"classification": "manual"}, "manual"),
        ({"stiction_advice": "test_valve"}, "valve"),
    ],
)
def test_each_reason_alone(changes: dict, reason: str) -> None:
    """One bad field gives exactly its reason and ready False."""
    assert loop_readiness(with_(**changes)) == {"ready": False, "reasons": [reason]}


def test_valve_row_overrides_kpi_row() -> None:
    """A valve row decides the valve reason; the KPI row's advice is then ignored."""
    row = with_(stiction_advice="test_valve")
    assert loop_readiness(row, {"stiction_advice": "unlikely"})["ready"] is True
    assert loop_readiness(GOOD, {"stiction_advice": "test_valve"})["reasons"] == ["valve"]


def test_reasons_accumulate_in_fixed_order() -> None:
    """Several failures are all listed: manual, saturated, pv_frozen, valve."""
    row = with_(
        service_factor=0.0, saturation_fraction=1.0, flatline_fraction=1.0,
        stiction_advice="test_valve",
    )
    assert loop_readiness(row)["reasons"] == ["manual", "saturated", "pv_frozen", "valve"]


def test_thresholds_are_arguments() -> None:
    """Limits come from the caller; a value at the limit is still ready."""
    row = with_(saturation_fraction=0.3)
    assert loop_readiness(row)["reasons"] == ["saturated"]
    assert loop_readiness(row, max_saturation=0.3)["ready"] is True
    assert loop_readiness(with_(service_factor=0.7), min_service_factor=0.8)["reasons"] == [
        "manual"
    ]
    assert loop_readiness(with_(flatline_fraction=0.2), max_flatline=0.1)["reasons"] == [
        "pv_frozen"
    ]


@pytest.mark.parametrize("value", [None, float("nan"), "x", True])
def test_unknown_values_are_not_reasons(value: object) -> None:
    """None, NaN and non-numbers mean unknown (withheld KPI), not a failure."""
    row = {"saturation_fraction": value, "flatline_fraction": value, "service_factor": value}
    assert loop_readiness(row) == {"ready": True, "reasons": []}
