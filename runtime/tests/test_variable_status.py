"""Tests for live variable status, anomaly flags and their store (Phase 2.5, step 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from crosscut_connectors.base import LiveValue, Snapshot
from crosscut_runtime.store import read_variable_status, write_variable_status
from crosscut_runtime.variable_status import (
    StatusInputs,
    VariableStatus,
    evaluate,
    flags_from_anomaly,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FRESH = "2026-01-01T11:59:50+00:00"
OLD = "2026-01-01T11:50:00+00:00"
CONTROLLER = {
    "id": "c1",
    "cycle_s": 30,
    "stale_cycles": 3,
    "variables": [
        {"id": "cv1", "role": "CV", "binding": {"tag": "t.cv"},
         "limits": {"validity": {"lo": 0, "hi": 100}}},
        {"id": "mv1", "role": "MV", "binding": {"loop": "L1"}},
        {"id": "dv1", "role": "DV", "binding": {"tag": "t.dv"}, "enabled_default": False},
    ],
}
TAGS = {"cv1": ["t.cv"], "mv1": ["t.pv", "t.sp"], "dv1": ["t.dv"]}


def _live(value: float = 50.0, quality: int = 0, stamp: str = FRESH) -> LiveValue:
    return LiveValue(value=value, quality=quality, timestamp_utc=stamp)


def _snapshot(comm_ok: bool = True, **overrides: LiveValue) -> Snapshot:
    values = {"t.cv": _live(), "t.pv": _live(), "t.sp": _live(), "t.dv": _live()}
    values.update({name.replace("_", ".", 1): live for name, live in overrides.items()})
    return Snapshot(cycle_utc=FRESH, values=values, comm_ok=comm_ok)


def _run(snapshot: Snapshot, **kwargs: object) -> dict[str, VariableStatus]:
    inputs = StatusInputs(snapshot, NOW, TAGS, disabled=frozenset(), **kwargs)  # type: ignore[arg-type]
    return {status.variable_id: status for status in evaluate(CONTROLLER, inputs)}


def test_all_good() -> None:
    result = _run(_snapshot())
    assert result["cv1"].status == "good" and result["cv1"].reasons == ()
    assert result["cv1"].value == 50.0 and result["cv1"].source_utc == FRESH


def test_comm_loss_is_bad_for_all() -> None:
    result = _run(_snapshot(comm_ok=False))
    assert {s.status for s in result.values()} == {"bad"}
    assert result["mv1"].reasons == ("comm_loss",)


def test_quality_uncertain_and_bad() -> None:
    assert _run(_snapshot(t_cv=_live(quality=1)))["cv1"].status == "uncertain"
    bad = _run(_snapshot(t_cv=_live(quality=2)))["cv1"]
    assert bad.status == "bad" and bad.reasons == ("quality",)


def test_stale_timestamp() -> None:
    result = _run(_snapshot(t_cv=_live(stamp=OLD)))["cv1"]
    assert result.status == "bad" and result.reasons == ("stale",)


def test_out_of_validity() -> None:
    result = _run(_snapshot(t_cv=_live(value=150.0)))["cv1"]
    assert result.status == "bad" and result.reasons == ("out_of_validity",)


def test_anomaly_flag_makes_bad() -> None:
    result = _run(_snapshot(), flags={"t.cv": {"anomaly"}})["cv1"]
    assert result.status == "bad" and result.reasons == ("anomaly",)


def test_worst_wins_and_reasons_accumulate() -> None:
    snap = _snapshot(t_cv=_live(value=150.0, quality=1, stamp=OLD))
    result = _run(snap)["cv1"]
    assert result.status == "bad"
    assert result.reasons == ("quality", "stale", "out_of_validity")


def test_operator_off_from_set_and_from_default() -> None:
    inputs = StatusInputs(_snapshot(), NOW, TAGS, disabled=frozenset({"cv1"}))
    by_id = {s.variable_id: s for s in evaluate(CONTROLLER, inputs)}
    assert by_id["cv1"].status == "bad" and by_id["cv1"].reasons == ("operator_off",)
    default = evaluate(CONTROLLER, StatusInputs(_snapshot(), NOW, TAGS))
    assert [s.status for s in default] == ["good", "good", "bad"]
    assert default[2].reasons == ("operator_off",)


def test_mv_covers_both_tags() -> None:
    result = _run(_snapshot(t_sp=_live(quality=2)))["mv1"]
    assert result.status == "bad" and result.tag == "t.pv"
    assert _run(_snapshot(t_pv=_live(stamp=OLD)))["mv1"].reasons == ("stale",)


def test_missing_tag_in_snapshot_is_bad() -> None:
    snap = Snapshot(cycle_utc=FRESH, values={}, comm_ok=True)
    assert _run(snap)["cv1"].reasons == ("quality",)


def test_flags_only_for_instrument_kinds() -> None:
    events = [
        {"kind": "stuck", "stuck_tag": "t.cv", "top_t2_tags": ["t.x"]},
        {"kind": "pca", "stuck_tag": None, "top_spe_tags": ["t.y"], "top_t2_tags": ["t.z"]},
        {"kind": "quality", "tag": "t.dv"},
    ]
    assert flags_from_anomaly(events) == {"t.cv": {"anomaly"}, "t.dv": {"anomaly"}}
    assert flags_from_anomaly(events, kinds=("pca",)) == {}


def test_store_round_trip(tmp_path: Path) -> None:
    assert read_variable_status(tmp_path) == {}
    first = [VariableStatus("cv1", "t.cv", "good", (), 1.0, FRESH)]
    write_variable_status(tmp_path, "c1", first)
    second = VariableStatus("v", None, "bad", ("stale",), None, None)
    write_variable_status(tmp_path, "c2", [second])
    document = read_variable_status(tmp_path)
    assert document["c1"][0]["variable_id"] == "cv1"
    assert document["c2"][0]["reasons"] == ["stale"]
    write_variable_status(tmp_path, "c1", [])
    assert read_variable_status(tmp_path)["c1"] == []
