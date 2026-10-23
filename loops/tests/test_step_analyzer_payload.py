"""Tests for the step analyzer payload and the cross-row consistency check.

The synthetic record mimics one loop: a manual double bump (FOPDT with known K, tau, theta
and additive noise) followed by a closed-loop setpoint bump, so both row kinds are exercised.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
from crosscut_loops.step_analyzer import analyze_steps
from crosscut_loops.step_consistency import add_consistency

DT_S = 10.0
N_SAMPLES = 1500
GAIN = 0.8
TAU_S = 120.0
THETA_S = 40.0
NOISE_SD = 0.15
ORIGIN_UTC_S = 1_700_000_000.0
TEST_LABEL = "bump-test-1"

STEP_1_SAMPLE = 200
STEP_1_FROM = 40.0
STEP_1_TO = 47.0
STEP_2_SAMPLE = 700
STEP_2_FROM = 47.0
STEP_2_TO = 41.0
SP_STEP_SAMPLE = 1100
SP_STEP_FROM = 50.0
SP_STEP_TO = 53.0

# Fixed seed so the noise realisation is deterministic across runs.
NOISE_SEED = 42


def _first_order_response(input_signal: np.ndarray, gain: float, tau_s: float, theta_s: float,
                          dt_s: float) -> np.ndarray:
    """Discrete FOPDT response: dead time then a first-order lag, PV relative to input start.

    The model is dPV/dt = (gain * dIN - dPV) / tau after theta seconds of delay; here we
    integrate the deviation from the initial input so the output starts at zero.
    """
    delay_samples = int(round(theta_s / dt_s))
    alpha = dt_s / (tau_s + dt_s)
    deviation = gain * (input_signal - input_signal[0])
    response = np.zeros_like(deviation)
    lagged = 0.0
    for i in range(len(deviation)):
        if i >= delay_samples:
            lagged += alpha * (deviation[i - delay_samples] - lagged)
        response[i] = lagged
    return response


def _build_record() -> dict:
    """Assemble the synthetic loop record with two OUT steps in manual and one SP step in auto."""
    rng = np.random.default_rng(NOISE_SEED)
    t_s = np.arange(N_SAMPLES) * DT_S

    out = np.full(N_SAMPLES, STEP_1_FROM)
    out[STEP_1_SAMPLE:STEP_2_SAMPLE] = STEP_1_TO
    out[STEP_2_SAMPLE:] = STEP_2_TO

    mode = np.zeros(N_SAMPLES)
    mode[SP_STEP_SAMPLE - 150 :] = 1.0  # auto starts well before the SP step (pre-step samples)

    # Manual segment: PV follows the FOPDT response to OUT plus measurement noise.
    pv_manual = 50.0 + _first_order_response(out, GAIN, TAU_S, THETA_S, DT_S)
    pv_manual += rng.normal(0.0, NOISE_SD, N_SAMPLES)

    # Auto segment: PV follows the setpoint smoothly (closed loop, no dead time).
    sp = np.full(N_SAMPLES, SP_STEP_FROM)
    sp[SP_STEP_SAMPLE:] = SP_STEP_TO
    pv_auto = _first_order_response(sp, 1.0, TAU_S, 0.0, DT_S) + 50.0

    pv = pv_manual.copy()
    pv[SP_STEP_SAMPLE:] = pv_auto[SP_STEP_SAMPLE:]
    # The controller reacts to the SP step: OUT drifts up by 2 % after it (needed for a fit).
    ramp = 1.0 - np.exp(-np.arange(N_SAMPLES - SP_STEP_SAMPLE) * DT_S / 60.0)
    out[SP_STEP_SAMPLE:] = out[SP_STEP_SAMPLE:] + 2.0 * ramp

    return {"t_s": t_s, "pv": pv, "sp": sp, "out": out, "mode": mode}


def _analyze(record: dict, **overrides) -> dict:
    """Run analyze_steps on the record with sensible defaults for the identifier fields."""
    options = {
        "loop_id": "TIC-101",
        "process_kind": "self_regulating",
        "unit": "°C",
        "origin_utc_s": ORIGIN_UTC_S,
        "test_windows": [],
        "logbook": [],
        "model": "auto",
    }
    options.update(overrides)
    return analyze_steps(**record, **options)


def _iso(unix_seconds: float) -> str:
    """Format Unix seconds as an ISO 8601 UTC string ending in Z."""
    moment = dt.datetime.fromtimestamp(unix_seconds, tz=dt.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows_by_kind(payload: dict, kind: str) -> list[dict]:
    """Return the payload rows whose kind matches."""
    return [row for row in payload["rows"] if row["kind"] == kind]


def _make_fopdt_row(gain: float, verdict: str = "ok") -> dict:
    """Build a minimal FOPDT payload row as add_consistency expects it."""
    return {
        "model": "fopdt",
        "verdict": verdict,
        "reasons": [],
        "params": {
            "gain": {"value": gain, "se": 0.01},
            "tau_s": {"value": 120.0, "se": 5.0},
            "theta_s": {"value": 40.0, "se": 2.0},
        },
    }


def test_payload_has_expected_top_level_keys():
    payload = _analyze(_build_record())
    expected = {
        "loop", "process_kind", "unit", "dt_s", "noise_sd", "n_events", "rows", "summary",
        "skipped",
    }
    assert expected.issubset(payload.keys())
    assert payload["loop"] == "TIC-101"


def test_rows_are_sorted_by_event_time():
    payload = _analyze(_build_record())
    event_times = [row["event_utc"] for row in payload["rows"]]
    assert event_times == sorted(event_times)


def test_out_step_rows_are_manual_and_open_loop():
    payload = _analyze(_build_record())
    out_rows = _rows_by_kind(payload, "out_step")
    assert out_rows
    for row in out_rows:
        assert row["mode"] == "manual"
        assert row["closed_loop"] is False


def test_first_out_step_gain_is_close_to_true_gain():
    payload = _analyze(_build_record())
    first = _rows_by_kind(payload, "out_step")[0]
    assert first["model"] == "fopdt"
    gain_value = first["params"]["gain"]["value"]
    assert abs(gain_value - GAIN) <= 0.1 * GAIN
    assert first["params"]["gain"]["se"] > 0


def test_sp_step_row_is_closed_loop_and_flags_the_reason():
    payload = _analyze(_build_record())
    sp_rows = _rows_by_kind(payload, "sp_step")
    assert sp_rows
    assert sp_rows[0]["closed_loop"] is True
    assert "closed_loop" in sp_rows[0]["reasons"]


def test_clean_first_step_is_ok():
    payload = _analyze(_build_record())
    first = _rows_by_kind(payload, "out_step")[0]
    assert first["verdict"] == "ok"


def test_first_step_has_large_signal_to_noise_ratio():
    payload = _analyze(_build_record())
    first = _rows_by_kind(payload, "out_step")[0]
    assert first["snr"] > 20.0


def test_test_label_matches_the_covering_window_only():
    record = _build_record()
    first_event = ORIGIN_UTC_S + STEP_1_SAMPLE * DT_S
    windows = [{
        "label": TEST_LABEL,
        "start_utc": _iso(first_event - 60.0),
        "end_utc": _iso(first_event + 60.0),
    }]
    payload = _analyze(record, test_windows=windows)
    rows = payload["rows"]
    assert rows[0]["test_label"] == TEST_LABEL
    assert rows[1]["test_label"] is None


def test_logbook_entries_within_window_are_attached():
    record = _build_record()
    first_event = ORIGIN_UTC_S + STEP_1_SAMPLE * DT_S
    logbook = [
        {"time_utc": _iso(first_event + 120.0), "text": "valve bumped"},
        {"time_utc": _iso(first_event + 600.0), "text": "too late"},
    ]
    payload = _analyze(record, logbook=logbook)
    texts = [entry["text"] for entry in payload["rows"][0]["logbook"]]
    assert texts == ["valve bumped"]


def test_payload_is_strict_json_serialisable():
    payload = _analyze(_build_record())
    json.dumps(payload, allow_nan=False)


def test_integrating_process_kind_forces_ipdt_model():
    payload = _analyze(_build_record(), process_kind="integrating")
    first = _rows_by_kind(payload, "out_step")[0]
    assert first["model"] == "ipdt"


def test_explicit_model_override_forces_fopdt():
    payload = _analyze(_build_record(), process_kind="integrating", model="fopdt")
    first = _rows_by_kind(payload, "out_step")[0]
    assert first["model"] == "fopdt"


def test_unknown_process_kind_with_auto_reports_alt_model():
    payload = _analyze(_build_record(), process_kind="unknown")
    fitted_rows = [row for row in payload["rows"] if row["model"] is not None]
    assert fitted_rows
    assert all("alt_model" in row for row in fitted_rows)
    assert any(row["alt_model"] is not None for row in fitted_rows)


def test_constant_record_has_no_events():
    flat = 50.0 * np.ones(N_SAMPLES)
    record = {
        "t_s": np.arange(N_SAMPLES) * DT_S,
        "pv": flat,
        "sp": flat,
        "out": flat,
        "mode": np.zeros(N_SAMPLES),
    }
    payload = _analyze(record)
    assert payload["rows"] == []
    assert payload["n_events"] == 0


def test_gain_outlier_is_marked_inconsistent_and_others_stay_ok():
    rows = [_make_fopdt_row(gain) for gain in [0.8, 0.82, 0.79, 0.81, 2.5]]
    summary = add_consistency(rows)
    assert rows[4]["verdict"] == "weak"
    assert "inconsistent_with_median" in rows[4]["reasons"]
    assert all(row["verdict"] == "ok" for row in rows[:4])
    assert summary[0]["n_rows"] == 5
    assert summary[0]["n_consistent"] == 4


def test_fewer_than_four_ok_rows_leaves_them_untouched():
    rows = [_make_fopdt_row(gain) for gain in [0.8, 0.82, 2.5]]
    summary = add_consistency(rows)
    assert all(row["verdict"] == "ok" for row in rows)
    assert all("inconsistent_with_median" not in row["reasons"] for row in rows)
    assert summary[0]["n_consistent"] == 3
