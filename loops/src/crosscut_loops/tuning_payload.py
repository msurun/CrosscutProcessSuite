"""JSON-ready payload of the tuning screen: window, model, fit check, settings, step preview.

Glues the existing pieces (identification and tuning rules in ``tuning_report``, model check and
step preview in ``tuning_view``) for one loop and one data window. Text for the user is returned as
codes (``blocked_code``, ``warnings``) so that the interface can translate it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from crosscut_loops.overview import LoopTags
from crosscut_loops.tuning_report import (
    DEFAULT_ROBUSTNESS,
    MODEL_FAILURE_PREFIX,
    POOR_FIT_PREFIX,
    TuningReport,
    build_tuning_report,
    render_markdown,
)
from crosscut_loops.tuning_view import closed_loop_step, fit_check, suggest_windows

MIN_WINDOW_S = 600.0  # shortest stretch worth proposing as a test window
MAX_CHECK_POINTS = 600  # points of the measured/simulated comparison sent to the browser
CLOSED_LOOP_SHARE = 0.1  # more than this share of non-MAN samples in the window = closed-loop data
MANUAL_MODE = 0.0


@dataclass(frozen=True)
class TuningRequest:
    """What the user chose: the window (None = best suggestion) and the robustness slider."""

    start_s: float | None = None
    end_s: float | None = None
    robustness: float = DEFAULT_ROBUSTNESS
    stiction_suspected: bool = False


@dataclass(frozen=True)
class WindowData:
    """One data window of a loop: time stamps, output u, process value y, sample time."""

    t_s: np.ndarray
    u: np.ndarray
    y: np.ndarray
    dt_s: float


JsonSeries = list[float] | list[float | None]


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
    # Search candidate windows on the controller output (the excitation signal) and the process
    # variable (the response); MIN_WINDOW_S is the shortest window worth fitting, in seconds.
    windows = suggest_windows(t_s, columns[loop.mode], columns[loop.out], MIN_WINDOW_S)
    # Pick the one window to show, either the caller's explicit start/end or the best suggestion.
    start_s, end_s = _chosen_window(t_s, windows, request)
    # Boolean mask selecting the samples inside [start_s, end_s]; kept as a mask so all columns
    # stay aligned sample by sample.
    keep = (t_s >= start_s) & (t_s <= end_s)
    # u = controller output (manipulated variable), y = process variable (measured response).
    u, y = columns[loop.out][keep], columns[loop.pv][keep]
    # Sampling period in seconds, taken as the median of the time differences so a single
    # irregular timestamp (a gap or a duplicate) does not distort it.
    dt_s = float(np.median(np.diff(t_s[keep])))
    # Bundle the aligned window for the fitting and reporting routines.
    window = WindowData(t_s=t_s[keep], u=u, y=y, dt_s=dt_s)
    report = _report_for(loop, window, request)
    # Fraction of samples in the window where the controller was in manual mode, in [0, 1]:
    # a high share means the operator drove the loop, so the data may not reflect the tuning.
    manual_share = float(np.mean(columns[loop.mode][keep] == MANUAL_MODE))
    return {
        "loop": loop.name,
        # Window-level fields: the suggested windows, the chosen span and the manual share.
        **_window_parts(windows, start_s, end_s, manual_share),
        "robustness": report.robustness,
        "blocked_code": _blocked_code(report),
        "markdown": render_markdown(report),
        # Model-level fields: the fitted model summary and its quality metrics.
        **_model_parts(report, window),
    }


def _window_parts(
    windows: list[tuple[float, float]], start_s: float, end_s: float, manual_share: float
) -> dict[str, object]:
    """Suggested windows, the chosen window and the data-quality warnings about it."""
    return {
        "windows": [{"start_s": start, "end_s": end} for start, end in windows],
        "window": {"start_s": start_s, "end_s": end_s, "manual_percent": round(100 * manual_share)},
        "warnings": ["closed_loop_data"] if 1.0 - manual_share > CLOSED_LOOP_SHARE else [],
    }


def _report_for(loop: LoopTags, window: WindowData, request: TuningRequest) -> TuningReport:
    """Identify the process from one window's time series and compute tuning parameters.

    TuningReport holds the identified model plus the PID settings derived from it,
    so one call does both steps. ``stiction`` (valve sticking, a mechanical fault that
    fakes oscillation) is passed on as evidence the downstream rules use to avoid
    tuning for what is really a hardware problem.

    Returns the veto-free report; raises whatever build_tuning_report raises on
    too-few samples or non-excitable data.
    """
    # "None" means stiction was not suspected, "stiction" means it was; the report
    # builder switches on the string, so we never invent a value, we pass a verdict or nothing.
    stiction = "stiction" if request.stiction_suspected else None
    # u: control output (0-100 %), y: measured process variable (engineering units),
    # dt_s: sample interval (s). build_tuning_report needs them plus the two user settings.
    return build_tuning_report(
        loop.name,
        window.u,
        window.y,
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

    Returns `(start_s, end_s)` in seconds. Never raises: a missing user request and an
    empty candidate list simply fall back to the whole record.
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
    """Model, fit check, settings and step preview; all None when no model was identified.

    `WindowData` holds one experiment: `t_s` (seconds), `u` (input), `y` (measured output)
    and `dt_s` (sample time in seconds). These arrays are what the identification was
    fitted on and what the fit check replays the model over.
    Returning a dict with fixed keys keeps the caller simple: it can render the payload
    even for a failed run, instead of branching on missing attributes.
    """
    if report.model is None or report.simc is None or report.amigo is None:
        return {"model": None, "fit": None, "check": None, "settings": None, "dcs_forms": {}}

    # `fit_check` simulates the identified model on the same input `u` and sampling
    # interval `dt_s` used for identification and compares it with the measured `y`.
    # `check` holds the scalar quality metrics; `simulated` is the model's response
    # over the same time base, so it can be drawn next to the real measurement.
    check, simulated = fit_check(report.model, window.u, window.y, window.dt_s)

    # A step response of the closed loop (controller `simc` + model) is the operator's
    # preview of how the loop would react; `step` carries three aligned arrays.
    step = closed_loop_step(report.model, report.simc)

    return {
        # `_plain` converts model objects (with numpy/array internals) to plain,
        # JSON-serialisable values for the front end.
        "model": _plain(report.model),
        # `r_squared` is the coefficient of determination, dimensionless, 1.0 = perfect.
        # Rounded to 3 decimals because more digits carry no meaning for the operator.
        "fit": {"verdict": check.verdict, "r_squared": round(check.r_squared, 3)},
        "check": _comparison(window.t_s, window.y, simulated),
        # The two controller settings that were tried, also reduced to plain values.
        "settings": {"simc": _plain(report.simc), "amigo": _plain(report.amigo)},
        # Alternative discrete controller forms considered, keyed by form name.
        "dcs_forms": report.dcs_forms,
        # Named tags of the Siemens and ABB blocks with evidence level and caveats.
        "vendor_forms": report.vendor_forms,
        # Numpy arrays are not JSON types; `tolist()` gives plain Python lists.
        # `t_s` is in seconds, `pv` is the process variable and `out` the controller output.
        "step": {"t_s": step.t_s.tolist(), "pv": step.pv.tolist(), "out": step.out.tolist()},
    }


def _plain(value: object) -> dict[str, float]:
    """Public numeric fields of a small dataclass as a dict."""
    return {name: float(number) for name, number in vars(value).items()}


def _comparison(
    t_s: np.ndarray, measured: np.ndarray, simulated: np.ndarray
) -> dict[str, JsonSeries]:
    """Measured and model PV on a common, thinned time axis.

    PV means photovoltaic: `measured` is what the plant really produced and
    `simulated` is what the model predicts, both sampled at the same instants.
    Building a plant-size report would embed every sample, so the curves are
    downsampled here to at most MAX_CHECK_POINTS points each.

    Returns a JSON-serialisable mapping, not arrays: the caller writes it to a
    report file, where numpy scalars would not survive the encoder.
    """
    # Indices of the samples to keep. np.linspace walks the whole array from
    # the first index (0) to the last (len(t_s) - 1) in equal steps, so the
    # thinned curve preserves the shape of the original; astype(int) turns the
    # floating fractions into valid positions. When the series is shorter than
    # MAX_CHECK_POINTS nothing is dropped and every index is returned.
    keep = np.linspace(0, len(t_s) - 1, min(MAX_CHECK_POINTS, len(t_s))).astype(int)
    return {
        # Same `keep` positions for all three series, so row i of `measured`
        # and row i of `simulated` refer to the same instant t_s[i].
        "t_s": t_s[keep].tolist(),
        "measured": _json_list(measured[keep]),
        "simulated": _json_list(simulated[keep]),
    }


def _json_list(values: np.ndarray) -> list[float | None]:
    """Values as a JSON-safe list: NaN has no JSON form, so it becomes None."""
    return [None if np.isnan(x) else float(x) for x in values]
