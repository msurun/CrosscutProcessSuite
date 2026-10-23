"""Tuning payload of an integrating loop, and the warnings that compare the two model kinds.

``ipdt_body`` builds the model, fit curve, settings, vendor forms and step preview of a loop
marked ``integrating``. ``looks_integrating`` (FOPDT path) and ``looks_self_regulating`` (IPDT
path) are warnings only; they never change settings.
"""

from __future__ import annotations

import numpy as np

from crosscut_loops.identification_ipdt import (
    IpdtFit,
    IpdtIdentificationError,
    fitted_pv,
    identify_ipdt,
)
from crosscut_loops.tuning_report import (
    MODEL_FAILURE_PREFIX,
    TuningReport,
    _clamp_robustness,
    identify_model,
)
from crosscut_loops.tuning_report_ipdt import (
    IpdtTuningReport,
    build_ipdt_report,
    render_ipdt_markdown,
)
from crosscut_loops.tuning_rules import FopdtModel
from crosscut_loops.tuning_series import comparison, json_list, thin_index
from crosscut_loops.tuning_types import TuningRequest, WindowData
from crosscut_loops.tuning_view import (
    GOOD_R_SQUARED,
    closed_loop_step_ipdt,
    fit_check,
    fit_verdict,
)

TAU_WINDOW_FACTOR = 3.0  # FOPDT time constant above this many windows looks like an integrator
IPDT_R2_MARGIN = 0.02  # IPDT may trail FOPDT by this much R2 and still count as explaining as well
Warnings = list[dict[str, object]]


def ipdt_body(
    loop_name: str, window: WindowData, request: TuningRequest
) -> tuple[dict[str, object], Warnings]:
    """Payload fields of an integrating loop plus its cross-model warnings."""
    swing = None
    if request.max_swing is not None and request.load_step_pct is not None:
        swing = (request.max_swing, request.load_step_pct)
    signals = (window.t_s, window.controller_output, window.process_value)
    robustness = _clamp_robustness(request.robustness)
    report = build_ipdt_report(loop_name, signals, robustness, swing, request.stiction_suspected)
    body: dict[str, object] = {
        "robustness": robustness,
        "blocked_code": report.blocked_code,
        "blocked_reasons": report.blocked_reasons,
        "markdown": render_ipdt_markdown(report),
        "invert_control": report.invert_control,
        "tau_c_s": report.tau_c_s,
        **_model_fields(report, window),
        **_settings_fields(report),
    }
    return body, looks_self_regulating(report, window)


def _model_fields(report: IpdtTuningReport, window: WindowData) -> dict[str, object]:
    """Model object, fit verdict, measured/model comparison and fitted ramp (None without a fit)."""
    fit = report.fit
    if fit is None:
        return {"model": None, "fit": None, "check": None, "fit_curve": None}
    curve = _curve(window, fit)
    if curve is None:
        return {"model": _model_object(fit), "fit": None, "check": None, "fit_curve": None}
    keep = thin_index(len(window.t_s))
    return {
        "model": _model_object(fit),
        "fit": {"verdict": fit_verdict(fit.r_squared), "r_squared": round(fit.r_squared, 3)},
        "check": comparison(window.t_s, window.process_value, curve),
        "fit_curve": {"t_s": window.t_s[keep].tolist(), "pv_model": json_list(curve[keep])},
    }


def _curve(window: WindowData, fit: IpdtFit) -> np.ndarray | None:
    """Fitted ramp over the window; None when the fit has no move to draw."""
    if "no_out_move" in fit.reasons:
        return None
    return fitted_pv(window.t_s, window.controller_output, window.process_value, fit.model.delay_s)


def _model_object(fit: IpdtFit) -> dict[str, object]:
    """The ``model`` object of kind ipdt; a non-finite error becomes None (JSON has no inf)."""
    return {
        "kind": "ipdt",
        "slope_per_s": fit.model.slope_per_s,
        "delay_s": fit.model.delay_s,
        "r_squared": fit.r_squared,
        "slope_rel_se": fit.slope_rel_se if np.isfinite(fit.slope_rel_se) else None,
        "up_down_ratio": fit.up_down_ratio,
        "baseline_slope": fit.baseline_slope,
        "verdict": fit.verdict,
        "reasons": list(fit.reasons),
    }


def _settings_fields(report: IpdtTuningReport) -> dict[str, object]:
    """Settings, forms and closed-loop step; the FOPDT-only fields (AMIGO, PID) stay empty."""
    if report.simc is None or report.fit is None:
        return {"settings": None, "dcs_forms": {}, "vendor_forms": {}, "step": None}
    step = closed_loop_step_ipdt(report.fit.model, report.simc)
    return {
        "settings": {"simc": {"kc": report.simc.kc, "ti_s": report.simc.ti_s}, "amigo": None},
        "dcs_forms": report.dcs_forms,
        "vendor_forms": report.vendor_forms,
        "vendor_forms_pid": {},
        "pid": None,
        "pid_advice": None,
        "step": {"t_s": step.t_s.tolist(), "pv": step.pv.tolist(), "out": step.out.tolist()},
    }


def looks_self_regulating(report: IpdtTuningReport, window: WindowData) -> Warnings:
    """Warn when a loop marked integrating fits no ramp (R2 < 0.8) but fits FOPDT well."""
    if report.fit is None or "r2_below_0.8" not in report.fit.reasons:
        return []
    model = identify_model(window.controller_output, window.process_value, window.dt_s)
    if model is None:
        return []
    check = fit_check(model, window.controller_output, window.process_value, window.dt_s)[0]
    if check.r_squared < GOOD_R_SQUARED:
        return []
    return [{"code": "looks_self_regulating", "fopdt_r_squared": round(check.r_squared, 3)}]


def looks_integrating(report: TuningReport, window: WindowData) -> Warnings:
    """Warn when a loop marked self-regulating behaves like an integrator.

    Three cases: the FOPDT time constant exceeds 3 window lengths; the FOPDT fit failed while an
    IPDT fit of the same window has R2 >= 0.8 and is not refused; or the FOPDT fit exists but the
    (not refused) IPDT fit has R2 >= 0.8 and explains the record at least as well as FOPDT
    (R2_ipdt >= R2_fopdt - IPDT_R2_MARGIN), reason ``ipdt_explains_record_as_well``.
    """
    window_s = float(window.t_s[-1] - window.t_s[0])
    if report.model is not None:
        if report.model.time_constant_s > TAU_WINDOW_FACTOR * window_s:
            tau = report.model.time_constant_s
            return [_integrating_warning("time_constant_over_3x_window", tau)]
        return _ipdt_as_good_as_fopdt(report.model, window)
    if report.blocked_reason is None or not report.blocked_reason.startswith(MODEL_FAILURE_PREFIX):
        return []
    fit = _try_ipdt(window)
    if fit is not None and fit.r_squared >= GOOD_R_SQUARED and fit.verdict != "blocked":
        return [_integrating_warning("model_failed_ipdt_fits", None, fit.r_squared)]
    return []


def _ipdt_as_good_as_fopdt(model: FopdtModel, window: WindowData) -> Warnings:
    """The ``ipdt_explains_record_as_well`` warning, or nothing."""
    fit = _try_ipdt(window)
    if fit is None or fit.verdict == "blocked" or fit.r_squared < GOOD_R_SQUARED:
        return []
    check = fit_check(model, window.controller_output, window.process_value, window.dt_s)[0]
    if fit.r_squared < check.r_squared - IPDT_R2_MARGIN:
        return []
    return [_integrating_warning("ipdt_explains_record_as_well", None, fit.r_squared)]


def _integrating_warning(
    reason: str, time_constant_s: float | None = None, r_squared: float | None = None
) -> dict[str, object]:
    """One ``looks_integrating`` entry with the number that triggered it."""
    return {
        "code": "looks_integrating",
        "reason": reason,
        "time_constant_s": time_constant_s,
        "ipdt_r_squared": None if r_squared is None else round(r_squared, 3),
    }


def _try_ipdt(window: WindowData) -> IpdtFit | None:
    """IPDT fit of the window, or None when the signals cannot be identified."""
    try:
        return identify_ipdt(window.t_s, window.controller_output, window.process_value)
    except IpdtIdentificationError:
        return None
