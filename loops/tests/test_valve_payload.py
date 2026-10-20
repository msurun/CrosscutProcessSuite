"""Tests for the valve stroke test JSON contract layer (request parsing, payloads, CSV)."""
# Synthetic records are built from a stick-slip valve + first-order process so the payload
# functions are tested against plausible data rather than hand-placed numbers.

from __future__ import annotations

import json

import numpy as np
import pytest
from crosscut_loops.valve_payload import (
    MAX_RECORD_POINTS,
    ValveInputError,
    analyse_window,
    parse_csv_record,
    plan_from_request,
    plan_payload,
)
from crosscut_loops.valve_test import plan_stroke_test

# Simulation constants (units: % of span for OP, PV units for process, seconds for time)
PROCESS_GAIN_PV_PER_PERCENT = 0.5  # dPV / dOP (PV units per % of span)
PROCESS_TAU_S = 5.0  # process time constant, seconds
VALVE_DEADBAND_PERCENT = 0.5  # valve stick width, % of span
PV_NOISE_SIGMA = 0.01  # PV noise standard deviation, PV units
SAMPLE_TIME_S = 1.0  # record sample interval, seconds
DWELL_S = 120  # dwell per step, seconds
RANDOM_SEED = 1234  # fixed so the synthetic record is reproducible


def _simulate_stroke_record(magnitude: float = 0.5) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate (t_s, op, pv) for a plan_stroke_test(op_start=50, dwell_s=120).

    The OP is piecewise constant (op_start, then each step target, held dwell_s samples).
    The valve is a stick-slip element: its position stays put until |OP - position| exceeds
    ``VALVE_DEADBAND_PERCENT``, then snaps to OP. The PV is a first-order lag of the valve
    position (dPV/dt = (K * position - PV) / tau) plus Gaussian noise. ``magnitude`` scales
    the whole PV so a caller can compare a moving valve with a flat response.
    """
    plan = plan_stroke_test(op_start=50.0, dwell_s=DWELL_S)
    op_profile_percent = [plan.op_start, *(step.op_target for step in plan.steps)]
    samples_per_level = int(DWELL_S / SAMPLE_TIME_S)
    op = np.repeat(op_profile_percent, samples_per_level).astype(float)
    n = len(op)

    valve_position = op[0]
    pv = np.empty(n)
    pv[0] = PROCESS_GAIN_PV_PER_PERCENT * valve_position * magnitude
    alpha = SAMPLE_TIME_S / (PROCESS_TAU_S + SAMPLE_TIME_S)
    rng = np.random.default_rng(RANDOM_SEED)
    for k in range(1, n):
        if abs(op[k] - valve_position) > VALVE_DEADBAND_PERCENT:
            valve_position = op[k]
        target = PROCESS_GAIN_PV_PER_PERCENT * valve_position * magnitude
        pv[k] = pv[k - 1] + alpha * (target - pv[k - 1]) + rng.normal(0.0, PV_NOISE_SIGMA)

    t_s = np.arange(n) * SAMPLE_TIME_S
    return t_s, op, pv


def _simulate_flat_pv_record() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OP moves as a plan but PV stays at zero: no gain is identifiable, noise-free."""
    plan = plan_stroke_test(op_start=50.0, dwell_s=DWELL_S)
    op_profile_percent = [plan.op_start, *(step.op_target for step in plan.steps)]
    samples_per_level = int(DWELL_S / SAMPLE_TIME_S)
    op = np.repeat(op_profile_percent, samples_per_level).astype(float)
    t_s = np.arange(len(op)) * SAMPLE_TIME_S
    pv = np.zeros(len(op))
    return t_s, op, pv


# --- ValveInputError -------------------------------------------------------------------


def test_valve_input_error_carries_code_and_field() -> None:
    error = ValveInputError("plan_invalid", "bad plan", "op_start")

    assert error.code == "plan_invalid"
    assert error.field == "op_start"
    assert str(error) == "bad plan"


def test_valve_input_error_is_a_value_error() -> None:
    error = ValveInputError("x", "message")

    assert isinstance(error, ValueError)
    assert error.field is None


# --- plan_from_request: happy path and defaults ----------------------------------------


def test_plan_from_request_uses_defaults_when_optional_keys_missing() -> None:
    plan = plan_from_request({"op_start": 50.0, "dwell_s": 120})

    assert plan.op_low == 0.0
    assert plan.op_high == 100.0
    assert plan.pv_band is None
    assert plan.step_sizes == (1.0, 0.25)
    assert plan.steps_per_leg == (4, 12)


def test_plan_from_request_accepts_explicit_values() -> None:
    plan = plan_from_request(
        {
            "op_start": 40.0,
            "dwell_s": 60,
            "op_low": 10.0,
            "op_high": 90.0,
            "pv_band": 2.0,
            "step_sizes": [0.5],
            "steps_per_leg": [3],
        }
    )

    assert plan.op_start == 40.0
    assert plan.op_high == 90.0
    assert plan.pv_band == 2.0
    assert plan.step_sizes == (0.5,)
    assert plan.steps_per_leg == (3,)


# --- plan_from_request: op_start / dwell_s validation ----------------------------------


def test_op_start_true_is_rejected_because_bool_is_not_a_number() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": True, "dwell_s": 120})

    assert info.value.field == "op_start"


def test_op_start_as_string_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": "50", "dwell_s": 120})

    assert info.value.code == "plan_invalid"


def test_op_start_nan_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": float("nan"), "dwell_s": 120})

    assert info.value.field == "op_start"


def test_dwell_zero_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 0})

    assert info.value.field == "dwell_s"


def test_dwell_negative_is_rejected() -> None:
    with pytest.raises(ValveInputError):
        plan_from_request({"op_start": 50.0, "dwell_s": -10})


def test_dwell_non_integer_float_is_rejected() -> None:
    with pytest.raises(ValveInputError):
        plan_from_request({"op_start": 50.0, "dwell_s": 120.5})


# --- plan_from_request: optional field validation --------------------------------------


def test_op_low_as_string_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "op_low": "ten"})

    assert info.value.field == "op_low"


def test_op_high_infinite_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "op_high": float("inf")})

    assert info.value.field == "op_high"


def test_pv_band_zero_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "pv_band": 0})

    assert info.value.field == "pv_band"


def test_pv_band_negative_is_rejected() -> None:
    with pytest.raises(ValveInputError):
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "pv_band": -1.0})


def test_pv_band_none_is_accepted() -> None:
    plan = plan_from_request({"op_start": 50.0, "dwell_s": 120, "pv_band": None})

    assert plan.pv_band is None


def test_step_sizes_empty_list_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "step_sizes": []})

    assert info.value.field == "step_sizes"


def test_step_sizes_negative_value_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "step_sizes": [-1.0]})

    assert info.value.field == "step_sizes"


def test_step_sizes_not_a_list_is_rejected() -> None:
    with pytest.raises(ValveInputError):
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "step_sizes": 1.0})


def test_steps_per_leg_zero_is_rejected() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "steps_per_leg": [0]})

    assert info.value.field == "steps_per_leg"


def test_steps_per_leg_non_integer_is_rejected() -> None:
    with pytest.raises(ValveInputError):
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "steps_per_leg": [1.5]})


def test_op_start_outside_limits_is_plan_invalid() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request({"op_start": 50.0, "dwell_s": 120, "op_low": 60.0, "op_high": 90.0})

    assert info.value.code == "plan_invalid"


def test_huge_steps_per_leg_is_plan_too_long() -> None:
    with pytest.raises(ValveInputError) as info:
        plan_from_request(
            {
                "op_start": 0.0,
                "dwell_s": 120,
                "op_low": -1000.0,
                "op_high": 1000.0,
                "step_sizes": [0.5],
                "steps_per_leg": [500],
            }
        )

    assert info.value.code == "plan_too_long"


# --- plan_payload ----------------------------------------------------------------------


def test_plan_payload_reports_step_count() -> None:
    plan = plan_stroke_test(op_start=50.0, dwell_s=120)
    payload = plan_payload(plan)

    assert payload["n_steps"] == len(plan.steps)


def test_plan_payload_total_s_counts_set_start_plus_every_dwell() -> None:
    plan = plan_stroke_test(op_start=50.0, dwell_s=120)
    payload = plan_payload(plan)

    assert payload["total_s"] == plan.dwell_s * (len(plan.steps) + 1)


def test_plan_payload_echoes_plan_parameters() -> None:
    plan = plan_stroke_test(op_start=40.0, dwell_s=90, step_sizes=(0.5,), steps_per_leg=(3,))
    payload = plan_payload(plan)

    assert payload["op_start"] == 40.0
    assert payload["dwell_s"] == 90
    assert payload["step_sizes"] == [0.5]
    assert payload["steps_per_leg"] == [3]


def test_plan_payload_has_one_entry_per_step() -> None:
    plan = plan_stroke_test(op_start=50.0, dwell_s=120)
    payload = plan_payload(plan)

    assert len(payload["steps"]) == len(plan.steps)
    assert payload["steps"][0]["index"] == 0


def test_plan_payload_procedure_codes_follow_the_operator_order() -> None:
    plan = plan_stroke_test(op_start=50.0, dwell_s=120, step_sizes=(1.0,), steps_per_leg=(2,))
    codes = [step["code"] for step in plan_payload(plan)["procedure"]]

    assert codes[:3] == ["manual", "abort", "set_start"]
    assert codes[-1] == "return_auto"
    assert codes[3:-1] == ["step"] * len(plan.steps)


def test_plan_payload_is_json_serialisable() -> None:
    plan = plan_stroke_test(op_start=50.0, dwell_s=120)

    text = json.dumps(plan_payload(plan))

    assert '"n_steps"' in text


# --- result_payload --------------------------------------------------------------------


def test_result_payload_of_complete_result_has_a_reason_code() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))["result"]

    assert payload["reason_code"] in ("", "no_move_after_reversal")


def test_result_payload_reports_no_gain_when_pv_is_flat() -> None:
    t_s, op, pv = _simulate_flat_pv_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))["result"]

    assert payload["reason_code"] == "no_gain"
    assert payload["gain"] is None


def test_result_payload_turns_nan_into_none() -> None:
    t_s, op, pv = _simulate_flat_pv_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))["result"]

    assert payload["deadband"] is None
    assert payload["resolution_le"] is None


def test_result_payload_is_json_serialisable() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))["result"]

    text = json.dumps(payload)

    assert "reason_code" in text


def test_result_payload_has_one_entry_per_move() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))["result"]

    assert len(payload["moves"]) >= 1
    assert "op_change" in payload["moves"][0]


# --- analyse_window --------------------------------------------------------------------


def test_whole_record_yields_a_deadband_bracket() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))

    assert payload["result"]["deadband_bracket"] is not None


def test_whole_record_series_is_decimated_to_the_limit() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))

    assert len(payload["record"]["series"]["t_s"]) <= MAX_RECORD_POINTS


def test_record_payload_reports_full_sample_count_of_the_window() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))

    assert payload["record"]["n_samples"] == len(t_s)


def test_window_cutting_the_record_narrows_the_series_times() -> None:
    t_s, op, pv = _simulate_stroke_record()
    payload = analyse_window(
        t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120), window=(0.0, 600.0)
    )

    assert payload["record"]["n_samples"] <= 601
    assert payload["record"]["end_s"] <= 600.0


def test_window_start_not_before_end_is_window_invalid() -> None:
    t_s, op, pv = _simulate_stroke_record()
    with pytest.raises(ValveInputError) as info:
        analyse_window(
            t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120), window=(100.0, 100.0)
        )

    assert info.value.code == "window_invalid"


def test_window_smaller_than_minimum_samples_is_record_too_short() -> None:
    t_s, op, pv = _simulate_stroke_record()
    with pytest.raises(ValveInputError) as info:
        analyse_window(
            t_s, op, pv, plan_stroke_test(op_start=50.0, dwell_s=120), window=(0.0, 10.0)
        )

    assert info.value.code == "record_too_short"


def test_nan_in_pv_is_record_not_finite() -> None:
    t_s, op, pv = _simulate_stroke_record()
    pv_with_nan = pv.copy()
    pv_with_nan[len(pv_with_nan) // 2] = np.nan
    with pytest.raises(ValveInputError) as info:
        analyse_window(t_s, op, pv_with_nan, plan_stroke_test(op_start=50.0, dwell_s=120))

    assert info.value.code == "record_not_finite"


def test_different_array_lengths_is_record_mismatch() -> None:
    t_s, op, pv = _simulate_stroke_record()
    with pytest.raises(ValveInputError) as info:
        analyse_window(t_s[:-1], op, pv, plan_stroke_test(op_start=50.0, dwell_s=120))

    assert info.value.code == "record_mismatch"


def test_constant_op_is_no_op_changes() -> None:
    plan = plan_stroke_test(op_start=50.0, dwell_s=120)
    length = 500
    t_s = np.arange(length) * SAMPLE_TIME_S
    op = np.full(length, 50.0)
    pv = np.zeros(length)
    with pytest.raises(ValveInputError) as info:
        analyse_window(t_s, op, pv, plan)

    assert info.value.code == "no_op_changes"


# --- parse_csv_record ------------------------------------------------------------------


def _csv_text(rows: list[list[str]], delimiter: str) -> str:
    return "\n".join(delimiter.join(row) for row in rows) + "\n"


def _numeric_rows(n: int, *, time_offset: float = 0.0, step_s: float = 1.0) -> list[list[str]]:
    return [
        [f"{time_offset + i * step_s:.3f}", f"{10.0 + i * 0.1:.3f}", f"{1.0 + i * 0.01:.3f}"]
        for i in range(n)
    ]


def test_comma_csv_with_header_resolves_columns_by_name() -> None:
    rows = [["t_s", "op", "pv"], *_numeric_rows(30)]
    t_s, op, pv = parse_csv_record(_csv_text(rows, ","))

    assert len(t_s) == 30
    assert op[0] == pytest.approx(10.0)


def test_semicolon_csv_with_decimal_comma_parses_numbers() -> None:
    rows = [["t", "op", "pv"], ["0,0", "10,5", "1,25"], ["1,0", "11,0", "1,30"]]
    rows += [[f"{i}.0", "12.0", "1.5"] for i in range(2, 30)]
    _t_s, op, _pv = parse_csv_record(_csv_text(rows, ";"))

    assert op[0] == pytest.approx(10.5)


def test_tab_separated_csv_parses() -> None:
    rows = [["t", "op", "pv"], *_numeric_rows(25)]
    t_s, _op, _pv = parse_csv_record(_csv_text(rows, "\t"))

    assert len(t_s) == 25


def test_bom_prefix_is_stripped_before_parsing() -> None:
    rows = [["t_s", "op", "pv"], *_numeric_rows(25)]
    _t_s, op, _pv = parse_csv_record("\ufeff" + _csv_text(rows, ","))

    assert op[0] == pytest.approx(10.0)


def test_headerless_csv_falls_back_to_positions() -> None:
    rows = _numeric_rows(25)
    t_s, op, _pv = parse_csv_record(_csv_text(rows, ","))

    assert len(t_s) == 25
    assert op[0] == pytest.approx(10.0)


def test_explicit_columns_mapping_selects_other_header_names() -> None:
    rows = [["time_stamp", "valve", "pressure"], *_numeric_rows(25)]
    _t_s, op, _pv = parse_csv_record(
        _csv_text(rows, ","),
        columns={"t": "time_stamp", "op": "valve", "pv": "pressure"},
    )

    assert op[1] == pytest.approx(10.1)


def test_iso_datetime_column_becomes_seconds_since_first_row() -> None:
    rows = [["t", "op", "pv"]]
    rows += [[f"2024-01-01T00:00:{i:02d}Z", "10.0", "1.0"] for i in range(30)]
    t_s, _op, _pv = parse_csv_record(_csv_text(rows, ","))

    assert t_s[0] == pytest.approx(0.0)
    assert t_s[1] == pytest.approx(1.0)


def test_rows_with_junk_are_skipped() -> None:
    rows = [["t", "op", "pv"], *_numeric_rows(25), ["bad", "x", "y"], ["nope", "", ""]]
    t_s, _op, _pv = parse_csv_record(_csv_text(rows, ","))

    assert len(t_s) == 25


def test_csv_text_over_the_limit_is_csv_too_large() -> None:
    text = "a" * 5_000_001
    with pytest.raises(ValveInputError) as info:
        parse_csv_record(text)

    assert info.value.code == "csv_too_large"


def test_two_columns_without_usable_names_is_csv_columns_missing() -> None:
    rows = [["alpha", "beta"], *[[f"{i}", f"{i}"] for i in range(25)]]
    with pytest.raises(ValveInputError) as info:
        parse_csv_record(_csv_text(rows, ","))

    assert info.value.code == "csv_columns_missing"


def test_too_few_numeric_rows_is_csv_no_numeric_rows() -> None:
    rows = [["t", "op", "pv"], *_numeric_rows(5)]
    with pytest.raises(ValveInputError) as info:
        parse_csv_record(_csv_text(rows, ","))

    assert info.value.code == "csv_no_numeric_rows"


def test_time_going_backwards_is_csv_time_not_increasing() -> None:
    rows = [["t", "op", "pv"]]
    rows += [[f"{30 - i}.0", "10.0", "1.0"] for i in range(30)]
    with pytest.raises(ValveInputError) as info:
        parse_csv_record(_csv_text(rows, ","))

    assert info.value.code == "csv_time_not_increasing"


def test_empty_csv_is_csv_no_numeric_rows() -> None:
    with pytest.raises(ValveInputError) as info:
        parse_csv_record("")

    assert info.value.code == "csv_no_numeric_rows"
