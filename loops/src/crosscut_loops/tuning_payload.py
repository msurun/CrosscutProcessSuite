"""JSON-ready payload of the tuning screen: window, model, fit check, settings, step preview.

Glues the existing pieces (identification and tuning rules in ``tuning_report``, model check and
step preview in ``tuning_view``) for one loop and one data window. Text for the user is returned as
codes (``blocked_code``, ``warnings``) so that the interface can translate it.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from crosscut_loops.overview import LoopTags
from crosscut_loops.tuning_payload_ipdt import ipdt_body, looks_integrating
from crosscut_loops.tuning_report import (
    MODEL_FAILURE_PREFIX,
    POOR_FIT_PREFIX,
    TuningReport,
    build_tuning_report,
    render_markdown,
)
from crosscut_loops.tuning_rules import FopdtModel
from crosscut_loops.tuning_series import comparison
from crosscut_loops.tuning_types import TuningRequest, WindowData
from crosscut_loops.tuning_view import closed_loop_step, fit_check, suggest_windows

MIN_WINDOW_S = 600.0  # shortest stretch worth proposing as a test window
CLOSED_LOOP_SHARE = 0.1  # more than this share of non-MAN samples in the window = closed-loop data
MANUAL_MODE = 0.0
INTEGRATING = "integrating"  # LoopTags.process_kind of a level loop



def tuning_payload(
    loop: LoopTags, t_s: np.ndarray, columns: Mapping[str, np.ndarray], request: TuningRequest
) -> dict[str, object]:
    """Everything the tuning screen needs for ``loop`` on the requested window.

    ``t_s`` is the shared time axis in seconds, monotonically increasing, one entry per sample.
    ``columns`` maps a signal name to its sample array on that same axis: ``columns[loop.mode]``
    is the controller mode code per sample, ``columns[loop.pv]`` the process variable (the
    measured output) and ``columns[loop.out]`` the controller output (the manipulated variable).
    The returned dict is the JSON-ready payload the tuning screen renders; keys are added in
    blocks so each group of fields stays easy to read.

    Returns:
        A dict with the loop name, the window metadata, the robustness verdict, the blocked-code
        explanation, the markdown notes, and the fitted model description.
    """
    # Candidate test windows are found from the controller mode and output columns;
    # MIN_WINDOW_S is the shortest window worth proposing, in seconds.
    windows = suggest_windows(t_s, columns[loop.mode], columns[loop.out], MIN_WINDOW_S)
    # Pick the one window to show, either the caller's explicit start/end or the best suggestion.
    start_s, end_s = _chosen_window(t_s, windows, request)
    # Boolean mask selecting the samples inside [start_s, end_s]; kept as a mask so all columns
    # stay aligned sample by sample.
    keep = (t_s >= start_s) & (t_s <= end_s)
    # Controller output (the manipulated variable) and process variable (the measured response)
    # inside the window.
    controller_output, process_value = columns[loop.out][keep], columns[loop.pv][keep]
    # Sampling period in seconds, taken as the median of the time differences so a single
    # irregular timestamp (a gap or a duplicate) does not distort it.
    dt_s = float(np.median(np.diff(t_s[keep])))
    # Bundle the aligned window for the fitting and reporting routines.
    window = WindowData(t_s[keep], controller_output, process_value, dt_s)
    body, model_warnings = _model_body(loop, window, request)
    # Fraction of samples in the window where the controller was in manual mode, in [0, 1]:
    # a high share means the operator drove the loop, so the data may not reflect the tuning.
    manual_share = float(np.mean(columns[loop.mode][keep] == MANUAL_MODE))
    return {
        "loop": loop.name,
        # Window-level fields: the suggested windows, the chosen span and the manual share.
        **_window_parts(windows, start_s, end_s, manual_share),
        # Model-level fields: model, fit, settings and the model-related warnings.
        **body,
        "warnings": [*_data_warnings(manual_share), *model_warnings],
    }


def _model_body(
    loop: LoopTags, window: WindowData, request: TuningRequest
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Payload fields that depend on the model kind, and the warnings of the model comparison."""
    if loop.process_kind == INTEGRATING:
        return ipdt_body(loop.name, window, request)
    report = _report_for(loop, window, request)
    body: dict[str, object] = {
        "robustness": report.robustness,
        "blocked_code": _blocked_code(report),
        "markdown": render_markdown(report),
        **_model_parts(report, window),
    }
    return body, looks_integrating(report, window)


def _window_parts(
    windows: list[tuple[float, float]], start_s: float, end_s: float, manual_share: float
) -> dict[str, object]:
    """Suggested windows, the chosen window and the data-quality warnings about it."""
    return {
        "windows": [{"start_s": start, "end_s": end} for start, end in windows],
        "window": {"start_s": start_s, "end_s": end_s, "manual_percent": round(100 * manual_share)},
    }


def _data_warnings(manual_share: float) -> list[dict[str, object]]:
    """Data-quality warnings about the window: closed-loop data."""
    return [{"code": "closed_loop_data"}] if 1.0 - manual_share > CLOSED_LOOP_SHARE else []


def _report_for(loop: LoopTags, window: WindowData, request: TuningRequest) -> TuningReport:
    """Identify the process from one window's time series and compute tuning parameters.

    TuningReport holds the identified model plus the PID settings derived from it,
    so one call does both steps. ``stiction`` (valve sticking, a mechanical fault that
    fakes oscillation) is passed on as evidence the downstream rules use to avoid
    tuning for what is really a hardware problem.

    Returns the report, which may be blocked (``blocked_reason``) or have no model when the
    identification failed (that failure does not raise).
    """
    # "None" means stiction was not suspected, "stiction" means it was; the report
    # builder switches on the string, so we never invent a value, we pass a verdict or nothing.
    stiction = "stiction" if request.stiction_suspected else None
    # Controller output (0-100 %), process variable (engineering units) and sample interval (s)
    # of the window, plus the two user settings: robustness and the stiction verdict.
    return build_tuning_report(
        loop.name,
        window.controller_output,
        window.process_value,
        window.dt_s,
        robustness=request.robustness,
        stiction_verdict=stiction,
    )


def _chosen_window(
    t_s: np.ndarray, windows: list[tuple[float, float]], request: TuningRequest
) -> tuple[float, float]:
    """Pick the time window the tuning should look at.

    `t_s` is the time axis of the record, in seconds, as a 1-D numpy array sorted from
    oldest to newest. `windows` is a list of candidate intervals, each `(start_s, end_s)`
    in seconds, ordered from best to worst by the caller (so index 0 is the top
    suggestion); it may be empty when no candidate was found.

    Returns `(start_s, end_s)` in seconds. A missing user request and an empty candidate list
    fall back to the whole record (which needs at least one timestamp).
    """
    # The user is the boss: when they gave both bounds we take them verbatim and ignore
    # every suggestion, even a better-looking one.
    if request.start_s is not None and request.end_s is not None:
        return request.start_s, request.end_s
    # No full user request: take the caller's first (best-ranked) suggestion. If there is
    # none, span the whole record from its first to its last timestamp. `float` guards
    # against numpy scalars leaking out of this function.
    return windows[0] if windows else (float(t_s[0]), float(t_s[-1]))


def _blocked_code(report: TuningReport) -> str | None:
    """Machine-readable reason why retuning is blocked, or None."""
    if report.blocked_reason is None:
        return None
    if report.blocked_reason.startswith(MODEL_FAILURE_PREFIX):
        return "model_failed"
    return "poor_fit" if report.blocked_reason.startswith(POOR_FIT_PREFIX) else "stiction"


def _model_parts(report: TuningReport, window: WindowData) -> dict[str, object]:
    """Model, fit check, settings and step preview; None (dcs_forms: {}) without a full model.

    `WindowData` holds one experiment: `t_s` (seconds), `controller_output` (input),
    `process_value` (measured output) and `dt_s` (sample time in seconds). These arrays are
    what the identification was fitted on and what the fit check replays the model over.
    Returning a dict with fixed keys keeps the caller simple: it can render the payload
    even for a failed run, instead of branching on missing attributes.
    """
    if report.model is None or report.simc is None or report.amigo is None:
        return {"model": None, "fit": None, "check": None, "settings": None, "dcs_forms": {}}

    # A step response of the closed loop (controller `simc` + model) is the operator's
    # preview of how the loop would react; `step` carries three aligned arrays.
    step = closed_loop_step(report.model, report.simc)
    return {
        **_fit_parts(report.model, window),
        **_settings_parts(report),
        # Numpy arrays are not JSON types; `tolist()` gives plain Python lists.
        # `t_s` is in seconds, `pv` is the process variable and `out` the controller output.
        "step": {"t_s": step.t_s.tolist(), "pv": step.pv.tolist(), "out": step.out.tolist()},
    }


def _fit_parts(model: FopdtModel, window: WindowData) -> dict[str, object]:
    """The model, its R-squared verdict and the measured-versus-simulated comparison."""
    # `fit_check` simulates the identified model on the same input and sampling
    # interval `dt_s` used for identification and compares it with the measured PV.
    # `check` holds the scalar quality metrics; `simulated` is the model's response
    # over the same time base, so it can be drawn next to the real measurement.
    check, simulated = fit_check(
        model, window.controller_output, window.process_value, window.dt_s
    )
    return {
        # `_plain` converts model objects (with numpy/array internals) to plain,
        # JSON-serialisable values for the front end.
        "model": {"kind": "fopdt", **_plain(model)},
        # `r_squared` is the coefficient of determination, dimensionless, 1.0 = perfect.
        # Rounded to 3 decimals because more digits carry no meaning for the operator.
        "fit": {"verdict": check.verdict, "r_squared": round(check.r_squared, 3)},
        "check": comparison(window.t_s, window.process_value, simulated),
    }


def _settings_parts(report: TuningReport) -> dict[str, object]:
    """Tuning settings of the report: PI rules, vendor forms and the PID advice."""
    return {
        # The two controller settings that were tried, also reduced to plain values.
        "settings": {"simc": _plain(report.simc), "amigo": _plain(report.amigo)},
        # Alternative discrete controller forms considered, keyed by form name.
        "dcs_forms": report.dcs_forms,
        # Named tags of the Siemens and ABB blocks with evidence level and caveats.
        "vendor_forms": report.vendor_forms,
        "vendor_forms_pid": report.vendor_forms_pid,
        # AMIGO PID (ideal form) and the advice whether derivative action is worth its noise.
        "pid": None if report.pid is None else _plain(report.pid),
        "pid_advice": None
        if report.pid_advice is None
        else {"use_derivative": report.pid_advice[0], "reason": report.pid_advice[1]},
    }


def _plain(value: object) -> dict[str, float]:
    """Public numeric fields of a small dataclass as a dict."""
    return {name: float(number) for name, number in vars(value).items()}
