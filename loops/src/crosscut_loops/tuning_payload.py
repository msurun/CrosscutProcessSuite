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
    """Everything the tuning screen needs for ``loop`` on the requested window."""
    windows = suggest_windows(t_s, columns[loop.mode], columns[loop.out], MIN_WINDOW_S)
    start_s, end_s = _chosen_window(t_s, windows, request)
    keep = (t_s >= start_s) & (t_s <= end_s)
    u, y = columns[loop.out][keep], columns[loop.pv][keep]
    dt_s = float(np.median(np.diff(t_s[keep])))
    window = WindowData(t_s=t_s[keep], u=u, y=y, dt_s=dt_s)
    report = _report_for(loop, window, request)
    manual_share = float(np.mean(columns[loop.mode][keep] == MANUAL_MODE))
    return {
        "loop": loop.name,
        **_window_parts(windows, start_s, end_s, manual_share),
        "robustness": report.robustness,
        "blocked_code": _blocked_code(report),
        "markdown": render_markdown(report),
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
    """Identification and tuning rules for one window; suspected stiction goes in as a verdict."""
    stiction = "stiction" if request.stiction_suspected else None
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
    """The user's window, else the best suggestion, else the whole record."""
    if request.start_s is not None and request.end_s is not None:
        return request.start_s, request.end_s
    return windows[0] if windows else (float(t_s[0]), float(t_s[-1]))


def _blocked_code(report: TuningReport) -> str | None:
    """Machine-readable reason why retuning is blocked, or None."""
    if report.blocked_reason is None:
        return None
    return "model_failed" if report.blocked_reason.startswith(MODEL_FAILURE_PREFIX) else "stiction"


def _model_parts(report: TuningReport, window: WindowData) -> dict[str, object]:
    """Model, fit check, settings and step preview; all None when no model was identified."""
    if report.model is None or report.simc is None or report.amigo is None:
        return {"model": None, "fit": None, "check": None, "settings": None, "dcs_forms": {}}
    check, simulated = fit_check(report.model, window.u, window.y, window.dt_s)
    step = closed_loop_step(report.model, report.simc)
    return {
        "model": _plain(report.model),
        "fit": {"verdict": check.verdict, "r_squared": round(check.r_squared, 3)},
        "check": _comparison(window.t_s, window.y, simulated),
        "settings": {"simc": _plain(report.simc), "amigo": _plain(report.amigo)},
        "dcs_forms": report.dcs_forms,
        "step": {"t_s": step.t_s.tolist(), "pv": step.pv.tolist(), "out": step.out.tolist()},
    }


def _plain(value: object) -> dict[str, float]:
    """Public numeric fields of a small dataclass as a dict."""
    return {name: float(number) for name, number in vars(value).items()}


def _comparison(
    t_s: np.ndarray, measured: np.ndarray, simulated: np.ndarray
) -> dict[str, JsonSeries]:
    """Measured and model PV on a common, thinned time axis."""
    keep = np.linspace(0, len(t_s) - 1, min(MAX_CHECK_POINTS, len(t_s))).astype(int)
    return {
        "t_s": t_s[keep].tolist(),
        "measured": _json_list(measured[keep]),
        "simulated": _json_list(simulated[keep]),
    }


def _json_list(values: np.ndarray) -> list[float | None]:
    """Values as a JSON-safe list: NaN has no JSON form, so it becomes None."""
    return [None if np.isnan(x) else float(x) for x in values]
