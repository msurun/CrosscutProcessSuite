# loops/tests/test_overview_dataset.py
"""Behaviour tests for crosscut_loops.overview.analyze_dataset."""

import json

import numpy as np
import pytest
from crosscut_loops.overview import LoopTags, analyze_dataset

# --- Constants describing the synthetic loop used across the tests -----------

SAMPLE_INTERVAL_S = 1.0
SAMPLE_COUNT = 4000
RANDOM_SEED = 0
NOISE_SCALE = 0.1

PV_BASE = 50.0
SP_BASE = 50.0
OUT_BASE = 40.0

MODE_AUTO = 1
MODE_UNUSED = 0

SPARKLINE_LENGTH = 48

# Upper bound of the controller output range; OUT stuck here means saturated.
OUT_FULL_SCALE = 100.0

SATURATION_FINDING_CODE = "saturated"
VALID_STATUS_LEVELS = {"ok", "warning", "problem"}


# --- Arrangement helpers ----------------------------------------------------


def _make_time_vector() -> np.ndarray:
    """Return a time vector of SAMPLE_COUNT seconds with one sample per second."""
    return np.arange(SAMPLE_COUNT, dtype=float) * SAMPLE_INTERVAL_S


def _make_auto_loop_columns() -> dict[str, np.ndarray]:
    """Return columns for a healthy loop in AUTO: PV and OUT jitter around fixed values."""
    noise = np.random.default_rng(RANDOM_SEED)
    return {
        "pv": PV_BASE + NOISE_SCALE * noise.standard_normal(SAMPLE_COUNT),
        "sp": np.full(SAMPLE_COUNT, SP_BASE),
        "out": OUT_BASE + NOISE_SCALE * noise.standard_normal(SAMPLE_COUNT),
    }


def _make_unused_loop_columns() -> dict[str, np.ndarray]:
    """Return a flat, time-invariant loop: nobody is tuning it, so mode is UNUSED."""
    noise = np.random.default_rng(RANDOM_SEED)
    return {
        "pv": PV_BASE + NOISE_SCALE * noise.standard_normal(SAMPLE_COUNT),
        "sp": np.full(SAMPLE_COUNT, SP_BASE),
        "out": np.full(SAMPLE_COUNT, OUT_BASE),
    }


def _make_saturated_loop_columns() -> dict[str, np.ndarray]:
    """Return a stuck loop: OUT clamped at full scale while PV drifts below SP."""
    return {
        "pv": np.linspace(SP_BASE - 10.0, SP_BASE - 5.0, SAMPLE_COUNT),
        "sp": np.full(SAMPLE_COUNT, SP_BASE),
        "out": np.full(SAMPLE_COUNT, OUT_FULL_SCALE),
    }


def _make_loop_tags(name: str, pv_tag: str, out_tag: str) -> LoopTags:
    """Return the tag description matching the synthetic columns above."""
    return LoopTags(
        name=name,
        pv=pv_tag,
        sp="SP",
        out=out_tag,
        mode="MODE",
        unit="degC",
        eng_min=0.0,
        eng_max=100.0,
    )


def _make_mode(mode_value: int) -> np.ndarray:
    """Return a constant controller mode column."""
    return np.full(SAMPLE_COUNT, mode_value)


# --- Tests ------------------------------------------------------------------


def test_the_result_has_one_entry_per_loop():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    results = analyze_dataset(time_vector, columns, [tags])

    assert len(results) == 1


def test_the_report_carries_all_expected_keys():
    time_vector = _make_time_vector()
    columns = _make_report_input_columns()
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert set(result) == _expected_report_keys()


def _make_report_input_columns():
    """Build the sample columns fed to the analyzer in this test."""
    auto_loop_columns = _make_auto_loop_columns()
    return {
        "PV": auto_loop_columns["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": auto_loop_columns["out"],
        "MODE": _make_mode(MODE_AUTO),
    }


def _expected_report_keys():
    """Return the set of keys every analysis report must expose."""
    return {
        "name",
        "pv",
        "sp",
        "out",
        "mode",
        "unit",
        "status",
        "health_percent",
        "classification",
        "findings",
        "service_percent",
        "saturation_percent",
        "harris_index",
        "oscillation_period_s",
        "stiction_verdict",
        "sparkline",
    }


def test_the_reported_ids_are_copied_from_the_loop_tags():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="reactor outlet", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert (result["name"], result["pv"], result["sp"], result["out"], result["mode"]) == (
        "reactor outlet",
        "PV",
        "SP",
        "OUT",
        "MODE",
    )


def test_the_unit_is_reported_from_the_loop_tags():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["unit"] == "degC"


def test_the_status_is_one_of_the_known_levels():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["status"] in VALID_STATUS_LEVELS


def test_the_sparkline_holds_exactly_48_points():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert len(result["sparkline"]) == SPARKLINE_LENGTH


def test_the_sparkline_carries_a_float_per_chunk():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert all(isinstance(value, float) for value in result["sparkline"])


def test_a_short_recording_yields_one_sparkline_point_per_sample():
    time_vector = np.arange(10, dtype=float) * SAMPLE_INTERVAL_S
    columns = {
        "PV": np.linspace(PV_BASE, PV_BASE + 1.0, 10),
        "SP": np.full(10, SP_BASE),
        "OUT": np.full(10, OUT_BASE),
        "MODE": np.full(10, MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert len(result["sparkline"]) == 10


def test_the_report_is_json_serialisable():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    results = analyze_dataset(time_vector, columns, [tags])

    assert json.dumps(results) is not None


def test_the_health_percent_is_none_when_the_loop_is_unused():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_unused_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_unused_loop_columns()["out"],
        "MODE": _make_mode(MODE_UNUSED),
    }
    tags = _make_loop_tags(name="spare loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["health_percent"] is None


def test_the_status_is_unused_when_the_mode_is_always_unused():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_unused_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_unused_loop_columns()["out"],
        "MODE": _make_mode(MODE_UNUSED),
    }
    tags = _make_loop_tags(name="spare loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["status"] == "unused"


def test_a_loop_pinned_at_full_output_is_flagged_as_saturated():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_saturated_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_saturated_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="stuck loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    finding_codes = {finding["code"] for finding in result["findings"]}
    assert SATURATION_FINDING_CODE in finding_codes


@pytest.mark.parametrize("expected_key", ["code", "params"])
def test_each_finding_has_a_code_and_params(expected_key):
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_saturated_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_saturated_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="stuck loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert all(expected_key in finding for finding in result["findings"])


def test_the_service_percent_is_a_rounded_integer():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert isinstance(result["service_percent"], int)


def test_two_loops_are_reported_in_input_order():
    time_vector = _make_time_vector()
    columns = {
        "PV": _make_auto_loop_columns()["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": _make_auto_loop_columns()["out"],
        "MODE": _make_mode(MODE_AUTO),
    }
    first = _make_loop_tags(name="first", pv_tag="PV", out_tag="OUT")
    second = _make_loop_tags(name="second", pv_tag="PV", out_tag="OUT")

    results = analyze_dataset(time_vector, columns, [first, second])

    assert [result["name"] for result in results] == ["first", "second"]
