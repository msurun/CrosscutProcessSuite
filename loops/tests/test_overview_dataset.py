# loops/tests/test_overview_dataset.py
"""Behaviour tests for crosscut_loops.overview.analyze_dataset."""

import json

import numpy as np
import pytest
from crosscut_loops.overview import LoopTags, _sparkline, analyze_dataset

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
        # Configured per-loop knowledge (the former placeholders), so every check is assessed.
        delay_s=30.0,
        ultimate_period_s=600.0,
        out_low=0.0,
        out_high=100.0,
    )


def _make_dataset_columns(loop_columns: dict[str, np.ndarray], mode_value: int) -> dict:
    """Return the PV/SP/OUT/MODE dataset for one loop, with a constant SP and mode."""
    return {
        "PV": loop_columns["pv"],
        "SP": np.full(SAMPLE_COUNT, SP_BASE),
        "OUT": loop_columns["out"],
        "MODE": _make_mode(mode_value),
    }


def _make_mode(mode_value: int) -> np.ndarray:
    """Return a constant controller mode column."""
    return np.full(SAMPLE_COUNT, mode_value)


# --- Tests ------------------------------------------------------------------


def test_the_result_has_one_entry_per_loop():
    """One tag set in gives one report row out, so rows map one-to-one to configured loops."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    results = analyze_dataset(time_vector, columns, [tags])

    assert len(results) == 1


def test_the_report_carries_all_expected_keys():
    """The report schema is a contract with the UI and exporters; no key may appear or vanish
    unnoticed."""
    time_vector = _make_time_vector()
    columns = _make_report_input_columns()
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert set(result) == EXPECTED_REPORT_KEYS


def _make_report_input_columns():
    """Build the sample columns fed to the analyzer in this test."""
    return _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)


# Keys every analysis report must expose.
EXPECTED_REPORT_KEYS = {
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
    "oscillation_method",
    "same_period_as",
    "stiction_verdict",
    "stiction_suspicion",
    "stiction_advice",
    "valve_travel_per_h",
    "valve_reversals_per_h",
    "out_quantisation_ratio",
    "valve_sizing_hint",
    "not_assessed",
    "sparkline",
    "next_action",
    "priority_rank",
}


def test_the_reported_ids_are_copied_from_the_loop_tags():
    """Name and tag ids in the report come straight from LoopTags, so the user can find the loop
    again."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
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
    """The engineering unit shown next to values is the one configured in LoopTags."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["unit"] == "degC"


def test_the_status_is_one_of_the_known_levels():
    """The status of a loop in use must be one of the levels the front end can colour."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["status"] in VALID_STATUS_LEVELS


def test_the_sparkline_holds_exactly_48_points():
    """A long recording is condensed to a fixed-width sparkline so all rows render alike."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert len(result["sparkline"]) == SPARKLINE_LENGTH


def test_the_sparkline_carries_a_float_per_chunk():
    """Sparkline values must be plain floats so the report serialises and plots as is."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert all(isinstance(value, float) for value in result["sparkline"])


def test_a_short_recording_yields_one_sparkline_point_per_sample():
    """A recording shorter than the sparkline width is not padded or resampled."""
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
    """The report is sent as JSON, so no numpy scalars or arrays may leak into it."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    results = analyze_dataset(time_vector, columns, [tags])

    # allow_nan=False also rejects NaN and infinity: missing values must already be None.
    encoded = json.dumps(results, allow_nan=False)
    assert json.loads(encoded)[0]["name"] == "loop 1"


def test_the_health_percent_is_none_when_the_loop_is_unused():
    """A loop nobody uses has no meaningful health score, so none is reported."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_unused_loop_columns(), MODE_UNUSED)
    tags = _make_loop_tags(name="spare loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["health_percent"] is None


def test_the_status_is_unused_when_the_mode_is_always_unused():
    """A loop whose mode is always UNUSED is labelled unused instead of ok or problem."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_unused_loop_columns(), MODE_UNUSED)
    tags = _make_loop_tags(name="spare loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert result["status"] == "unused"


def test_a_loop_pinned_at_full_output_is_flagged_as_saturated():
    """An output stuck at its upper limit must raise the saturated finding, the main sign of a stuck
    valve or a bad tune."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_saturated_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="stuck loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    finding_codes = {finding["code"] for finding in result["findings"]}
    assert SATURATION_FINDING_CODE in finding_codes


@pytest.mark.parametrize("expected_key", ["code", "params"])
def test_each_finding_has_a_code_and_params(expected_key):
    """Every finding carries a machine code and parameters so the UI can translate and fill in its
    text."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_saturated_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="stuck loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert all(expected_key in finding for finding in result["findings"])


def test_the_service_percent_is_a_rounded_integer():
    """The service percentage is reported as a whole number for display."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="loop 1", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    assert isinstance(result["service_percent"], int)


def test_two_loops_are_reported_in_input_order():
    """Rows keep the order of the tag list so the user can match them to their own configuration."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_auto_loop_columns(), MODE_AUTO)
    first = _make_loop_tags(name="first", pv_tag="PV", out_tag="OUT")
    second = _make_loop_tags(name="second", pv_tag="PV", out_tag="OUT")

    results = analyze_dataset(time_vector, columns, [first, second])

    assert [result["name"] for result in results] == ["first", "second"]


def test_the_saturated_finding_carries_the_window_of_the_saturated_stretch():
    """A saturated finding points at the stretch where the output was clamped, here the whole
    record."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_saturated_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="stuck loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    saturated = next(
        finding for finding in result["findings"] if finding["code"] == SATURATION_FINDING_CODE
    )
    assert saturated["window_s"] == [0.0, time_vector[-1]]


def test_a_finding_about_the_whole_record_has_no_window():
    """Oscillation and stiction findings describe the whole record, so they must not carry a
    window_s."""
    time_vector = _make_time_vector()
    columns = _make_dataset_columns(_make_saturated_loop_columns(), MODE_AUTO)
    tags = _make_loop_tags(name="stuck loop", pv_tag="PV", out_tag="OUT")

    [result] = analyze_dataset(time_vector, columns, [tags])

    unwindowed = [
        finding for finding in result["findings"] if finding["code"] in ("oscillating", "stiction")
    ]
    assert all("window_s" not in finding for finding in unwindowed)


def test_a_series_with_a_partial_last_block_keeps_its_tail_samples():
    """97 samples in 48 points: the 97th sample must reach the last point, not be dropped."""
    pv = np.ones(97)
    pv[-1] = 49.0

    sparkline = _sparkline(pv, points=SPARKLINE_LENGTH)

    assert len(sparkline) == SPARKLINE_LENGTH
    assert sparkline[-1] == pytest.approx(25.0)


# --- Shared oscillation period ("same_period_as") ----------------------------

PERIOD_SAMPLE_S = 10.0
PERIOD_SAMPLE_COUNT = 2160
PERIOD_NOISE_SCALE = 0.05
SLOW_PERIOD_S = 600.0
OTHER_PERIOD_S = 1500.0


def _make_period_time_vector() -> np.ndarray:
    """Return a time vector of PERIOD_SAMPLE_COUNT samples, PERIOD_SAMPLE_S seconds apart."""
    return np.arange(PERIOD_SAMPLE_COUNT, dtype=float) * PERIOD_SAMPLE_S


def _make_sine_loop_columns(period_s: float, seed: int) -> dict[str, np.ndarray]:
    """Return AUTO-mode columns for a loop whose error is a unit sine of the given period."""
    t_s = _make_period_time_vector()
    noise = np.random.default_rng(seed)
    return {
        "pv": SP_BASE
        + np.sin(2.0 * np.pi * t_s / period_s)
        + PERIOD_NOISE_SCALE * noise.standard_normal(PERIOD_SAMPLE_COUNT),
        "sp": np.full(PERIOD_SAMPLE_COUNT, SP_BASE),
        "out": OUT_BASE + PERIOD_NOISE_SCALE * noise.standard_normal(PERIOD_SAMPLE_COUNT),
    }


def _make_white_noise_loop_columns(seed: int) -> dict[str, np.ndarray]:
    """Return AUTO-mode columns for a loop whose PV is unit white noise: no regular cycle."""
    noise = np.random.default_rng(seed)
    return {
        "pv": SP_BASE + noise.standard_normal(PERIOD_SAMPLE_COUNT),
        "sp": np.full(PERIOD_SAMPLE_COUNT, SP_BASE),
        "out": OUT_BASE + PERIOD_NOISE_SCALE * noise.standard_normal(PERIOD_SAMPLE_COUNT),
    }


def _make_period_tags(name: str, index: int) -> LoopTags:
    """Return the LoopTags for loop number `index`, whose columns are PV<index> .. MODE<index>."""
    return LoopTags(
        name=name,
        pv=f"PV{index}",
        sp=f"SP{index}",
        out=f"OUT{index}",
        mode=f"MODE{index}",
        unit="degC",
        eng_min=0.0,
        eng_max=100.0,
    )


def _make_period_recording(
    loop_columns: dict[str, dict[str, np.ndarray]],
) -> tuple[dict[str, np.ndarray], list[LoopTags]]:
    """Return the shared columns and the LoopTags for several loops, one tag set per loop.

    No oscillation limits are configured, so the period comes from the parameter-free detector.
    """
    columns: dict[str, np.ndarray] = {}
    tags: list[LoopTags] = []
    for index, (name, loop) in enumerate(loop_columns.items(), start=1):
        columns[f"PV{index}"] = loop["pv"]
        columns[f"SP{index}"] = loop["sp"]
        columns[f"OUT{index}"] = loop["out"]
        columns[f"MODE{index}"] = np.full(PERIOD_SAMPLE_COUNT, MODE_AUTO)
        tags.append(_make_period_tags(name, index))
    return columns, tags


def test_loops_cycling_at_the_same_period_list_each_other():
    """Loops that oscillate with the same period are linked, which hints at a common cause; a quiet
    loop is not."""
    loops = {
        "slow A": _make_sine_loop_columns(SLOW_PERIOD_S, seed=1),
        "slow B": _make_sine_loop_columns(SLOW_PERIOD_S, seed=2),
        "quiet": _make_white_noise_loop_columns(seed=3),
    }
    columns, tags = _make_period_recording(loops)

    rows = analyze_dataset(_make_period_time_vector(), columns, tags)

    by_name = {row["name"]: row for row in rows}
    assert by_name["slow A"]["oscillation_period_s"] is not None
    assert by_name["slow A"]["same_period_as"] == ["slow B"]
    assert by_name["slow B"]["same_period_as"] == ["slow A"]
    assert by_name["quiet"]["same_period_as"] == []
    assert all(isinstance(row["same_period_as"], list) for row in rows)


def test_loops_cycling_at_clearly_different_periods_list_no_peers():
    """Loops with clearly different periods are not linked, so unrelated oscillations are not blamed
    on one cause."""
    loops = {
        "slow": _make_sine_loop_columns(SLOW_PERIOD_S, seed=1),
        "other": _make_sine_loop_columns(OTHER_PERIOD_S, seed=2),
    }
    columns, tags = _make_period_recording(loops)

    rows = analyze_dataset(_make_period_time_vector(), columns, tags)

    by_name = {row["name"]: row for row in rows}
    assert by_name["slow"]["oscillation_period_s"] is not None
    assert by_name["other"]["oscillation_period_s"] is not None
    assert by_name["slow"]["same_period_as"] == []
    assert by_name["other"]["same_period_as"] == []
    assert all(isinstance(row["same_period_as"], list) for row in rows)
