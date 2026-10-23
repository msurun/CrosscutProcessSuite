"""Tuning payload of integrating loops: routing, refusal, tuning, warnings (synthetic records)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from crosscut_loops.identification_ipdt import fitted_pv, identify_ipdt
from crosscut_loops.overview import LoopTags
from crosscut_loops.tuning_payload import tuning_payload
from crosscut_loops.tuning_rules import PiSettings
from crosscut_loops.tuning_types import TuningRequest
from crosscut_loops.tuning_view import MAX_PREVIEW_STEPS, closed_loop_step_ipdt

K = 0.002  # PV unit per second per % OUT
THETA = 20.0
N = 1200
T = np.arange(N, dtype=float)
MODEL_KEYS = {
    "kind", "slope_per_s", "delay_s", "delay_lower_s", "delay_upper_s", "delay_used_s",
    "r_squared", "slope_rel_se", "up_down_ratio",
    "baseline_slope", "verdict", "reasons",
}  # fmt: skip


def _loop(kind: str) -> LoopTags:
    return LoopTags("LIC1", "pv", "sp", "out", "mode", "m", None, None, process_kind=kind)


def _out(moves: list[tuple[float, float]]) -> np.ndarray:
    u = np.full(N, 50.0)
    for at, delta in moves:
        u[T >= at] += delta
    return u


def _ramp(u: np.ndarray, drift: float = 0.0, noise: float = 0.0, k: float = K) -> np.ndarray:
    ud = np.interp(T - THETA, T, u) - u[0]
    integral = np.concatenate(([0.0], np.cumsum(0.5 * (ud[1:] + ud[:-1]))))
    y = 10.0 + drift * T + k * integral
    return y + np.random.default_rng(3).normal(0.0, noise, N) if noise else y


def _first_order(u: np.ndarray, gain: float = 1.5, tau: float = 60.0) -> np.ndarray:
    y = np.zeros(N)
    for i in range(1, N):
        j = max(i - 5, 0)
        y[i] = y[i - 1] + (gain * (u[j] - u[0]) - y[i - 1]) / tau
    return 10.0 + y + np.random.default_rng(4).normal(0.0, 0.01, N)


def _payload(kind: str, u: np.ndarray, pv: np.ndarray, **request: object) -> dict:
    columns = {"pv": pv, "sp": pv, "out": u, "mode": np.zeros(N)}
    body = tuning_payload(_loop(kind), T, columns, TuningRequest(0.0, float(N - 1), **request))
    return json.loads(json.dumps(body))  # must be JSON-clean


def _codes(body: dict) -> list[str]:
    return [warning["code"] for warning in body["warnings"]]


def test_a_clean_ramp_gives_ipdt_settings_vendor_forms_and_a_fit_curve() -> None:
    u = _out([(300, 5)])
    body = _payload("integrating", u, _ramp(u))
    model = body["model"]
    assert set(model) == MODEL_KEYS and model["kind"] == "ipdt" and model["verdict"] == "ok"
    assert model["slope_per_s"] == pytest.approx(K, rel=0.05) and model["reasons"] == []
    assert body["blocked_code"] is None and body["blocked_reasons"] == []
    simc = body["settings"]["simc"]
    assert simc["kc"] > 0 and simc["ti_s"] > 0 and body["settings"]["amigo"] is None
    siemens = body["vendor_forms"]["siemens_pid_compact"]["tags"]
    assert siemens["Retain.CtrlParams.Gain"] == pytest.approx(simc["kc"])
    assert siemens["Retain.CtrlParams.Ti"] == pytest.approx(simc["ti_s"])
    assert siemens["Config.InvertControl"] is False and body["invert_control"] is False
    assert body["vendor_forms"]["abb_pidcc"]["block"] and body["dcs_forms"]
    assert set(body["fit_curve"]) == {"t_s", "pv_model"} and body["warnings"] == []
    assert len(body["step"]["t_s"]) == len(body["step"]["pv"]) > 10


def test_tau_c_follows_the_robustness_mapping() -> None:
    u = _out([(300, 5)])
    fast = _payload("integrating", u, _ramp(u), robustness=0.0)["settings"]["simc"]
    robust = _payload("integrating", u, _ramp(u), robustness=1.0)["settings"]["simc"]
    assert robust["kc"] < fast["kc"] and robust["ti_s"] > fast["ti_s"]


def test_a_negative_slope_inverts_the_controller_action() -> None:
    u = _out([(300, 5)])
    body = _payload("integrating", u, _ramp(u, k=-K))
    assert body["invert_control"] is True
    assert body["vendor_forms"]["siemens_pid_compact"]["tags"]["Config.InvertControl"] is True
    assert body["settings"]["simc"]["kc"] > 0


def test_max_swing_sets_tau_c_from_the_load_step() -> None:
    u = _out([(300, 5)])
    body = _payload("integrating", u, _ramp(u), max_swing=2.0, load_step_pct=4.0)
    kc_min = 4.0 / 2.0  # Kc_min = load / swing
    assert body["settings"]["simc"]["kc"] == pytest.approx(kc_min, rel=0.1)
    assert body["tau_c_s"] >= body["model"]["delay_s"]


@pytest.mark.parametrize("given", [{"max_swing": 1.0}, {"load_step_pct": 1.0}])
def test_a_swing_limit_needs_the_load_step_and_the_reverse(given: dict) -> None:
    with pytest.raises(ValueError, match="together"):
        TuningRequest(**given)


@pytest.mark.parametrize("swing, load", [(0.0, 1.0), (1.0, -2.0)])
def test_swing_and_load_step_must_be_positive(swing: float, load: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        TuningRequest(max_swing=swing, load_step_pct=load)


def test_a_refused_fit_returns_codes_and_no_settings() -> None:
    u = _out([(100, 5)])  # move at the start: no lead before it
    body = _payload("integrating", u, _ramp(u, noise=0.002))
    assert body["blocked_code"] == "ipdt_refused"
    assert "pre_move_lead_under_20pct" in body["blocked_reasons"]
    assert body["settings"] is None and body["dcs_forms"] == {} and body["step"] is None
    assert body["model"]["kind"] == "ipdt" and body["model"]["verdict"] == "blocked"


def test_no_out_move_is_refused_with_a_json_clean_payload() -> None:
    body = _payload("integrating", _out([]), np.full(N, 10.0))
    assert body["blocked_code"] == "ipdt_refused" and body["blocked_reasons"] == ["no_out_move"]
    assert body["model"]["slope_rel_se"] is None and body["fit_curve"] is None


def test_a_low_confidence_fit_still_gives_settings_with_a_note() -> None:
    u = _out([(250, 5), (500, -10), (750, 5)])
    steps = np.diff(u, prepend=u[0])
    weak_down = u[0] + np.cumsum(np.where(steps < 0, 0.7 * steps, steps))  # down gain is 70 %
    body = _payload("integrating", u, _ramp(weak_down))
    model = body["model"]
    assert model["verdict"] == "low_confidence" and "up_down_differ_over_25pct" in model["reasons"]
    assert body["blocked_code"] is None and body["settings"]["simc"]["kc"] > 0
    assert "low confidence" in body["markdown"]


def test_the_fitted_curve_follows_the_noise_free_ramp() -> None:
    u = _out([(300, 5)])
    pv = _ramp(u)
    fit = identify_ipdt(T, u, pv)
    assert np.max(np.abs(fitted_pv(T, u, pv, fit.model.delay_s) - pv)) < 0.05


def test_the_ipdt_step_preview_settles_on_the_setpoint_and_is_bounded() -> None:
    from crosscut_loops.identification_ipdt import IpdtModel

    preview = closed_loop_step_ipdt(IpdtModel(K, THETA), PiSettings(1 / (K * 40.0), 160.0))
    assert preview.pv[-1] == pytest.approx(1.0, abs=0.05) and preview.pv.max() < 1.6
    tiny = closed_loop_step_ipdt(IpdtModel(K, 1e-6), PiSettings(1.0, 1e6))
    assert len(tiny.t_s) <= MAX_PREVIEW_STEPS


def test_a_normal_fopdt_loop_has_kind_fopdt_and_no_warnings() -> None:
    u = _out([(300, 5)])
    body = _payload("self_regulating", u, _first_order(u))
    assert body["model"]["kind"] == "fopdt" and body["warnings"] == []
    assert "fit_curve" not in body and "blocked_reasons" not in body


def test_a_ramp_on_a_self_regulating_loop_warns_it_looks_integrating() -> None:
    u = _out([(300, 5)])
    body = _payload("self_regulating", u, _ramp(u, noise=0.002))
    warning = [w for w in body["warnings"] if w["code"] == "looks_integrating"]
    assert warning and body["markdown"]  # warning only: the FOPDT answer is unchanged
    again = _payload("self_regulating", u, _ramp(u, noise=0.002))
    assert again["settings"] == body["settings"]


def test_ipdt_explains_record_as_well_fires_on_a_ramp_but_not_on_a_settling_fopdt() -> None:
    from crosscut_loops.tuning_payload_ipdt import looks_integrating
    from crosscut_loops.tuning_report import TuningReport
    from crosscut_loops.tuning_rules import FopdtModel
    from crosscut_loops.tuning_types import WindowData

    u = _out([(300, 5)])
    model = FopdtModel(gain=1.0, time_constant_s=300.0, delay_s=20.0)
    report = TuningReport("LIC1", model, None, None)
    ramp = WindowData(T, u, _ramp(u, noise=0.002), 1.0)
    assert [w["reason"] for w in looks_integrating(report, ramp)] == [
        "ipdt_explains_record_as_well"
    ]
    settled = WindowData(T, u, _first_order(u, gain=1.0, tau=60.0), 1.0)
    fast = FopdtModel(gain=1.0, time_constant_s=60.0, delay_s=5.0)
    assert looks_integrating(TuningReport("LIC1", fast, None, None), settled) == []


def test_a_first_order_response_on_an_integrating_loop_warns_it_looks_self_regulating() -> None:
    u = _out([(300, 5), (400, -5), (500, 5), (600, -5), (700, 5), (800, -5)])
    body = _payload("integrating", u, _first_order(u, tau=20.0))
    assert body["blocked_code"] == "ipdt_refused" and "r2_below_0.8" in body["blocked_reasons"]
    assert "looks_self_regulating" in _codes(body)
    assert body["settings"] is None


def test_closed_loop_data_is_now_a_warning_object() -> None:
    u = _out([(300, 5)])
    columns = {"pv": _ramp(u), "sp": _ramp(u), "out": u, "mode": np.ones(N)}
    request = TuningRequest(0.0, float(N - 1))
    body = tuning_payload(_loop("integrating"), T, columns, request)
    assert {"code": "closed_loop_data"} in body["warnings"]


def test_settings_use_upper_delay_and_payload_keys() -> None:
    """Kc with the upper dead time is smaller than with the point estimate; keys are present."""
    from crosscut_loops.tuning_rules_integrating import (
        lambda_from_robustness_integrating,
        simc_pi_integrating,
    )

    u = _out([(300, 5)])
    pv = _ramp(u, noise=0.01)
    model = _payload("integrating", u, pv)["model"]
    assert model["delay_lower_s"] <= model["delay_s"] <= model["delay_upper_s"]
    assert model["delay_used_s"] == model["delay_upper_s"]
    assert model["delay_upper_s"] > model["delay_s"]
    body = _payload("integrating", u, pv, robustness=0.5)
    slope, point = model["slope_per_s"], model["delay_s"]
    tau_point = lambda_from_robustness_integrating(point, 0.5)
    kc_point = simc_pi_integrating(slope, point, tau_point).kc
    assert body["settings"]["simc"]["kc"] < kc_point
