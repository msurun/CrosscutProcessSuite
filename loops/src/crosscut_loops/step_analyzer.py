"""Step analyzer: orchestrates event detection and model fitting into the JSON payload.

Reads historian signals, finds step tests with step_events, fits FOPDT/IPDT models
with step_fit, computes verdicts and aligns test labels/logbook. Analysis only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_loops.step_consistency import add_consistency
from crosscut_loops.step_events import (
    find_step_events,
    robust_noise_sd,
)
from crosscut_loops.step_fit import Param, StepFit, StepFitError, fit_step

# Maximum number of points in the per-row sample payload (for GUI display).
MAX_SAMPLE_POINTS = 300

# Number of pre/post fractions used for amplitude estimation.
AMPLITUDE_POST_FRACTION = 0.2

# Minimum signal-to-noise ratio for a useful step response.
MIN_SNR = 5.0

# Maximum relative standard error of gain/slope for a useful step response.
MAX_SE_RELATIVE = 0.3

# Minimum R² for a useful step response.
MIN_R2 = 0.5

# Logbook matching window in seconds around the event.
LOGBOOK_WINDOW_S = 300.0

# Fit model selection keywords.
PROCESS_KIND_INTEGRATING = "integrating"
PROCESS_KIND_SELF_REGULATING = "self_regulating"


@dataclass(frozen=True)
class _RowContext:
    """Internal context for building one row: event, slices, and reference values."""

    event_index: int
    i0: int
    i1: int
    pre: int
    pre_seconds: float
    post_seconds: float
    window_t_s: np.ndarray
    window_pv: np.ndarray
    window_out: np.ndarray


def analyze_steps(
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
    *,
    loop_id: str,
    process_kind: str,
    unit: str,
    origin_utc_s: float,
    test_windows: list[dict],
    logbook: list[dict],
    model: str = "auto",
) -> dict[str, Any]:
    """Analyze step tests in one dataset loop and return a JSON-safe payload.

    Args:
        t_s: Sample times in seconds since the first sample (1-D).
        pv: Process variable samples (1-D).
        sp: Setpoint samples (1-D).
        out: Controller output samples (1-D).
        mode: Mode samples (1-D), 0=manual, 1=auto.
        loop_id: Loop identifier (e.g. "TIC-101").
        process_kind: "integrating" or "self_regulating".
        unit: Engineering unit of the PV (e.g. "°C").
        origin_utc_s: Unix seconds of t_s[0].
        test_windows: List of {"label", "start_utc", "end_utc"} with ISO text times.
        logbook: List of {"time_utc", "text"} with ISO text times.
        model: "auto", "fopdt", or "ipdt".

    Returns:
        Dict with keys loop, process_kind, unit, dt_s, noise_sd, n_events, rows, skipped.
    """
    t_array, pv_array, sp_array, out_array, mode_array = _validate_analyze_inputs(
        t_s, pv, sp, out, mode
    )
    dt_s = _median_dt(t_array)
    events, skipped_events = find_step_events(
        t_array, pv_array, sp_array, out_array, mode_array, dt_s
    )
    noise_pv = robust_noise_sd(pv_array)

    rows = []
    for event_index, event in enumerate(events):
        row = _build_row(
            event_index=event_index,
            t_s=t_array,
            pv=pv_array,
            out=out_array,
            event=event,
            dt_s=dt_s,
            origin_utc_s=origin_utc_s,
            process_kind=process_kind,
            unit=unit,
            test_windows=test_windows,
            logbook=logbook,
            model=model,
            noise_pv=noise_pv,
        )
        rows.append(row)

    summary = add_consistency(rows)
    skipped = [
        {"event_utc": _iso_from_seconds(origin_utc_s + float(item.t_s)), "reason": item.reason}
        for item in skipped_events
    ]

    return {
        "loop": loop_id,
        "process_kind": process_kind,
        "unit": unit,
        "dt_s": _json_float(dt_s),
        "noise_sd": _json_float(noise_pv),
        "n_events": len(events),
        "rows": rows,
        "summary": summary,
        "skipped": skipped,
    }


def _validate_analyze_inputs(
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Cast signals to float arrays and check common lengths."""
    arrays = tuple(np.asarray(signal, dtype=float) for signal in (t_s, pv, sp, out, mode))
    lengths = {array.size for array in arrays}
    if len(lengths) != 1:
        raise ValueError("t_s, pv, sp, out and mode must have the same length")
    if any(array.ndim != 1 for array in arrays):
        raise ValueError("all input arrays must be 1-D")
    return arrays


def _median_dt(t_s: np.ndarray) -> float:
    """Return the median sample period in seconds; fallback to 1 s for short arrays."""
    if len(t_s) < 2:
        return 1.0
    diffs = np.diff(np.asarray(t_s, dtype=float))
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size == 0:
        return 1.0
    return float(np.median(diffs))


def _build_row(
    *,
    event_index: int,
    t_s: np.ndarray,
    pv: np.ndarray,
    out: np.ndarray,
    event: Any,
    dt_s: float,
    origin_utc_s: float,
    process_kind: str,
    unit: str,
    test_windows: list[dict],
    logbook: list[dict],
    model: str,
    noise_pv: float,
) -> dict[str, Any]:
    """Build one row of the payload for a single detected step."""
    context = _make_context(t_s, pv, out, event)

    # Fit the model(s).
    fit_result, alt_model = _fit_event_with_selection(context, process_kind, model)

    # Compute row fields, including verdict and alignment.
    return _assemble_row(
        event_index=event_index,
        event=event,
        context=context,
        origin_utc_s=origin_utc_s,
        test_windows=test_windows,
        logbook=logbook,
        noise_pv=noise_pv,
        fit_result=fit_result,
        alt_model=alt_model,
    )


def _make_context(t_s, pv, out, event) -> _RowContext:
    """Slice the window arrays for one event and compute reference values."""
    i0, i1 = event.i0, event.i1
    pre = event.pre
    window_t_s = t_s[i0:i1]
    window_pv = pv[i0:i1]
    window_out = out[i0:i1]
    pre_seconds = float(window_t_s[pre] - window_t_s[0])
    post_seconds = float(window_t_s[-1] - window_t_s[pre])
    return _RowContext(
        event_index=event.i,
        i0=i0,
        i1=i1,
        pre=pre,
        pre_seconds=pre_seconds,
        post_seconds=post_seconds,
        window_t_s=window_t_s,
        window_pv=window_pv,
        window_out=window_out,
    )


def _fit_event_with_selection(
    context: _RowContext, process_kind: str, model: str
) -> tuple[StepFit | StepFitError, dict[str, Any] | None]:
    """Fit one model, or both with BIC selection when neither the caller nor the loop picks one.

    A forced ``model`` or a known ``process_kind`` (integrating -> IPDT, self_regulating -> FOPDT)
    fits that model only (half the work); only an unknown kind in 'auto' fits both and keeps the
    lower BIC, reporting the other as ``alt_model``.

    Returns:
        (fit or error, alt_model dict or None).
    """
    if model in ("fopdt", "ipdt"):
        return _try_fit(context, model), None
    by_kind = {PROCESS_KIND_INTEGRATING: "ipdt", PROCESS_KIND_SELF_REGULATING: "fopdt"}
    if process_kind in by_kind:
        return _try_fit(context, by_kind[process_kind]), None
    fits = [_try_fit(context, name) for name in ("fopdt", "ipdt")]
    good = [f for f in fits if not isinstance(f, StepFitError)]
    if not good:
        return fits[0], None
    best = min(good, key=lambda f: f.bic)
    others = [f for f in good if f is not best]
    alt = {"model": others[0].model, "bic": _json_float(others[0].bic)} if others else None
    return best, alt


def _try_fit(context: _RowContext, model: str) -> StepFit | StepFitError:
    """Try to fit one model; return the error on failure."""
    try:
        return fit_step(
            context.window_t_s,
            context.window_pv,
            context.window_out,
            context.pre,
            model,
        )
    except StepFitError as error:
        return error


def _assemble_row(
    *,
    event_index: int,
    event: Any,
    context: _RowContext,
    origin_utc_s: float,
    test_windows: list[dict],
    logbook: list[dict],
    noise_pv: float,
    fit_result: StepFit | StepFitError,
    alt_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the JSON payload row for one event."""
    row: dict[str, Any] = {}
    row["id"] = str(event_index)
    row["kind"] = event.kind
    row["mode"] = event.mode
    row["closed_loop"] = event.kind == "sp_step"
    row["start_utc"] = _iso_from_seconds(origin_utc_s + float(context.window_t_s[0]))
    row["event_utc"] = _iso_from_seconds(origin_utc_s + float(event.t_s))
    row["end_utc"] = _iso_from_seconds(origin_utc_s + float(context.window_t_s[-1]))
    row["size"] = _json_float(event.size)

    if isinstance(fit_result, StepFitError):
        row["snr"] = None
        row["model"] = None
        row["r2"] = None
        row["rmse"] = None
        row["n"] = len(context.window_pv)
        row["verdict"] = "unusable"
        row["reasons"] = ["fit_failed"]
        row["alt_model"] = None
        row["test_label"] = _test_label(origin_utc_s + event.t_s, test_windows)
        row["logbook"] = _logbook_entries(origin_utc_s + event.t_s, logbook)
        row["sample"] = _sample_payload(context, None)
        row["detail"] = str(fit_result)
        return row

    # Fit succeeded.
    model_name = fit_result.model
    snr = _compute_snr(context, fit_result, noise_pv)
    params = _params_dict(fit_result)
    reasons = _verdict_reasons(fit_result, snr, event.kind)
    verdict = _verdict(reasons, event.kind)

    row["snr"] = _json_float(snr)
    row["model"] = model_name
    row["params"] = params
    row["r2"] = _json_float(fit_result.r2)
    row["rmse"] = _json_float(fit_result.rmse)
    row["n"] = fit_result.n
    row["verdict"] = verdict
    row["reasons"] = reasons
    row["alt_model"] = alt_model
    row["test_label"] = _test_label(origin_utc_s + event.t_s, test_windows)
    row["logbook"] = _logbook_entries(origin_utc_s + event.t_s, logbook)
    row["sample"] = _sample_payload(context, fit_result)
    return row


def _params_dict(fit: StepFit) -> dict[str, dict[str, float | None]]:
    """Build the params dict, omitting absent parameters."""
    params: dict[str, dict[str, float | None]] = {}
    _add_param(params, "gain", fit.gain)
    _add_param(params, "tau_s", fit.tau_s)
    _add_param(params, "theta_s", fit.theta_s)
    _add_param(params, "slope", fit.slope)
    return params


def _add_param(params: dict, name: str, param: Param | None) -> None:
    """Add a parameter with value and se, skipping None params."""
    if param is None:
        return
    params[name] = {"value": _json_float(param.value), "se": _json_float(param.se)}


def _compute_snr(context: _RowContext, fit: StepFit, noise_pv: float) -> float:
    """Compute signal-to-noise ratio for the fitted step response."""
    if noise_pv <= 0:
        return float("inf")
    if fit.model == "fopdt":
        amplitude = _fopdt_amplitude(context)
    else:
        amplitude = _ipdt_amplitude(context, fit)
    return amplitude / noise_pv


def _fopdt_amplitude(context: _RowContext) -> float:
    """Amplitude for FOPDT: difference of medians between pre and last 20 % of post."""
    pre_pv = context.window_pv[: context.pre]
    post_all = context.window_pv[context.pre :]
    post_pv = post_all[int(len(post_all) * (1 - AMPLITUDE_POST_FRACTION)) :]
    if pre_pv.size == 0 or post_pv.size == 0:
        return 0.0
    return abs(float(np.nanmedian(post_pv)) - float(np.nanmedian(pre_pv)))


def _ipdt_amplitude(context: _RowContext, fit: StepFit) -> float:
    """Amplitude for IPDT: |slope| * |out change| * post span in seconds.

    This is the model-implied PV change over the post-event window: the integrator gain
    (PV per second per OUT unit) times the average OUT change times the post-step duration.
    """
    if fit.slope is None:
        return 0.0
    pre_out = context.window_out[: context.pre]
    post_out = context.window_out[context.pre :]
    if pre_out.size == 0 or post_out.size == 0:
        return 0.0
    out_change = abs(float(np.nanmedian(post_out)) - float(np.nanmedian(pre_out)))
    return abs(fit.slope.value) * out_change * context.post_seconds


def _verdict_reasons(fit: StepFit, snr: float, event_kind: str) -> list[str]:
    """Build the list of reason codes for the row verdict."""
    reasons: list[str] = []
    if snr < MIN_SNR:
        reasons.append("snr_low")
    if _se_over_threshold(fit):
        reasons.append("gain_se_over_30pct")
    if fit.r2 < MIN_R2:
        reasons.append("r2_low")
    reasons.extend(fit.edges)
    if event_kind == "sp_step":
        reasons.append("closed_loop")
    return reasons


def _se_over_threshold(fit: StepFit) -> bool:
    """Check whether gain/slope relative standard error exceeds 30 %."""
    param = fit.gain if fit.model == "fopdt" else fit.slope
    if param is None or param.value == 0 or not np.isfinite(param.se):
        return False
    return abs(param.se / param.value) > MAX_SE_RELATIVE


def _verdict(reasons: list[str], event_kind: str) -> str:
    """Determine verdict from reasons; closed_loop alone does not make a row weak."""
    weak_reasons = {"snr_low", "gain_se_over_30pct", "r2_low", "theta_at_edge", "tau_at_edge"}
    significant = [r for r in reasons if r in weak_reasons]
    return "ok" if not significant else "weak"


def _test_label(event_time_s: float, test_windows: list[dict]) -> str | None:
    """Find the first test window label containing the event time, else None."""
    for window in test_windows:
        try:
            start = _parse_iso_utc(window["start_utc"])
            end = _parse_iso_utc(window["end_utc"])
        except (KeyError, ValueError):
            continue
        if start <= event_time_s <= end:
            return str(window.get("label"))
    return None


def _logbook_entries(event_time_s: float, logbook: list[dict]) -> list[dict]:
    """Return logbook entries within ±300 s of the event time."""
    entries: list[dict] = []
    for entry in logbook:
        try:
            time_s = _parse_iso_utc(entry["time_utc"])
        except (KeyError, ValueError):
            continue
        if abs(time_s - event_time_s) <= LOGBOOK_WINDOW_S:
            entries.append({"time_utc": str(entry["time_utc"]), "text": str(entry.get("text", ""))})
    return entries


def _sample_payload(context: _RowContext, fit: StepFit | None) -> dict[str, list[float]]:
    """Thin the window samples to at most MAX_SAMPLE_POINTS for the payload.

    The returned t_s is relative to the window start (seconds), pv and out are raw,
    and fit is None when no model was fitted.
    """
    n = len(context.window_pv)
    if n <= MAX_SAMPLE_POINTS:
        indices = np.arange(n)
    else:
        indices = np.linspace(0, n - 1, MAX_SAMPLE_POINTS, dtype=int)
    t_rel = context.window_t_s - context.window_t_s[0]
    payload = {
        "t_s": [_json_float(v) for v in t_rel[indices]],
        "pv": [_json_float(v) for v in context.window_pv[indices]],
        "out": [_json_float(v) for v in context.window_out[indices]],
    }
    if fit is not None:
        payload["fit"] = [_json_float(v) for v in fit.fitted[indices]]
    return payload


def _iso_from_seconds(unix_seconds: float) -> str:
    """Convert Unix seconds to an ISO 8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)."""
    import datetime as _dt

    return _dt.datetime.fromtimestamp(float(unix_seconds), tz=_dt.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _parse_iso_utc(text: str) -> float:
    """Parse an ISO UTC timestamp (with Z or offset) to Unix seconds; raises ValueError."""
    import datetime as _dt

    text = str(text).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = _dt.datetime.fromisoformat(text)
    return float(parsed.timestamp())


def _json_float(value: Any) -> float | None:
    """Convert numpy scalars/inf/NaN to JSON-safe float or None."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    return result
