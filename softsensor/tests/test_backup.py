"""Tests of the backup mode: each outage kind on synthetic data, hysteresis without chatter,
the switch log, the quality codes and the config checks (every field required, no defaults)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from crosscut_softsensor.backup import (
    BACKUP,
    GOOD,
    MEASURED,
    SUBSTITUTED,
    UNAVAILABLE,
    run_backup,
)
from crosscut_softsensor.config import BackupConfig, SoftSensorConfigError, load_config

PERIOD = 60.0
CFG = BackupConfig("an", frozen_s=300.0, range_lo=0.0, range_hi=100.0, return_hold_s=300.0,
                   flag_tag="an.flag")
SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas"
                     / "softsensor.schema.json").read_text("utf-8"))


def _series(n: int = 60) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Time, a moving measurement (never exactly repeating) and a virtual value of 50."""
    t = PERIOD * np.arange(n)
    return t, 40.0 + np.sin(np.arange(n)), np.full(n, 50.0)


def _reasons(result_switches: list[dict[str, object]]) -> list[str]:
    return [str(s["reason"]) for s in result_switches]


def test_healthy_measurement_passes_through_with_no_switch() -> None:
    t, m, v = _series()
    res = run_backup(t, m, None, v, CFG)
    assert res.switches == [] and not res.substituted.any()
    assert np.array_equal(res.output, m) and (res.quality == GOOD).all()


def test_bad_quality_is_substituted_then_returns_after_the_hold() -> None:
    t, m, v = _series()
    m[10:15] = np.nan  # five bins without a good sample
    res = run_backup(t, m, None, v, CFG)
    assert _reasons(res.switches) == ["bad_quality", "measurement_valid"]
    assert res.switches[0] == {"t_s": 600.0, "from": MEASURED, "to": BACKUP,
                               "reason": "bad_quality"}
    # valid again at row 15, back after return_hold_s = 5 bins -> row 20
    assert res.switches[1]["t_s"] == 20 * PERIOD
    assert res.substituted[10:20].all() and not res.substituted[20:].any()
    assert (res.output[10:20] == 50.0).all() and (res.quality[10:20] == SUBSTITUTED).all()


def test_out_of_range_is_substituted() -> None:
    t, m, v = _series()
    m[5:8] = 130.0
    res = run_backup(t, m, None, v, CFG)
    assert res.switches[0]["reason"] == "out_of_range" and res.substituted[5]


def test_frozen_value_is_substituted_after_frozen_s() -> None:
    t, m, v = _series()
    m[20:35] = 41.0  # constant for 15 bins = 900 s
    res = run_backup(t, m, None, v, CFG)
    first = res.switches[0]
    assert first["reason"] == "frozen" and first["t_s"] == (20 + 5) * PERIOD  # 300 s unchanged
    assert not res.substituted[24] and res.substituted[25]


def test_analyser_flag_is_substituted() -> None:
    t, m, v = _series()
    flag = np.zeros(len(t))
    flag[30:33] = 1.0
    res = run_backup(t, m, flag, v, CFG)
    assert res.switches[0]["reason"] == "analyser_flag" and res.substituted[30]


def test_flickering_around_a_limit_does_not_chatter() -> None:
    t, m, v = _series(80)
    m[10:50:2] = 130.0  # alternating invalid / valid every bin for 40 bins
    res = run_backup(t, m, None, v, CFG)
    entries = [s for s in res.switches if s["to"] == BACKUP]
    assert len(res.switches) == 2 and len(entries) == 1  # one substitution, one return
    assert res.substituted[10:50].all()


def test_no_model_value_means_unavailable_quality() -> None:
    t, m, v = _series()
    m[10:12] = np.nan
    v[10:12] = np.nan
    res = run_backup(t, m, None, v, CFG)
    assert (res.quality[10:12] == UNAVAILABLE).all() and np.isnan(res.output[10:12]).all()


def test_zero_hold_returns_on_the_first_valid_row() -> None:
    t, m, v = _series()
    m[10:12] = np.nan
    cfg = BackupConfig("an", 300.0, 0.0, 100.0, 0.0)
    res = run_backup(t, m, None, v, cfg)
    assert res.switches[1]["t_s"] == 12 * PERIOD


def _doc(**backup: object) -> dict[str, object]:
    return {"schema_version": "1.0.0", "id": "t", "target_tag": "y", "input_tags": ["a"],
            "mode": "advisory", "backup": {"enabled": True, "measured_tag": "an", "frozen_s": 300,
                                           "range_lo": 0, "range_hi": 100, "return_hold_s": 600,
                                           **backup}}


def test_valid_backup_config_loads_and_matches_the_schema() -> None:
    doc = _doc(flag_tag="f")
    jsonschema.validate(doc, SCHEMA)
    cfg = load_config(doc).backup
    assert cfg == BackupConfig("an", 300.0, 0.0, 100.0, 600.0, "f")


def test_disabled_or_absent_backup_is_none() -> None:
    assert load_config({**_doc(), "backup": {"enabled": False}}).backup is None
    doc = _doc()
    del doc["backup"]
    assert load_config(doc).backup is None


@pytest.mark.parametrize("missing", ["measured_tag", "frozen_s", "range_lo", "range_hi",
                                     "return_hold_s"])
def test_every_field_is_required_when_enabled(missing: str) -> None:
    doc = _doc()
    del doc["backup"][missing]  # type: ignore[attr-defined]
    with pytest.raises(SoftSensorConfigError, match=f"backup.{missing}"):
        load_config(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)


@pytest.mark.parametrize("bad", [{"range_lo": 100}, {"frozen_s": 0}, {"return_hold_s": -1},
                                 {"extra": 1}, {"flag_tag": ""}])
def test_bad_backup_values_are_refused_naming_the_field(bad: dict[str, object]) -> None:
    with pytest.raises(SoftSensorConfigError, match="backup"):
        load_config(_doc(**bad))


def test_nan_flag_is_unknown_not_good_but_zero_flag_is_ok() -> None:
    """Issue #126: a configured flag with no value must not pass the measurement as GOOD."""
    t, m, v = _series()
    flag = np.zeros(len(t))
    flag[10] = np.nan
    res = run_backup(t, m, flag, v, CFG)
    assert res.reason[10] == "analyser_flag_unknown" and res.substituted[10]
    assert res.quality[10] == SUBSTITUTED
    assert res.reason[5] == "" and res.quality[5] == GOOD  # flag 0 stays OK
    only_unknown = run_backup(t, m, flag, np.full(len(t), np.nan), CFG)
    assert only_unknown.quality[10] == UNAVAILABLE
