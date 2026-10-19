"""Tune a loop from historian data without a dedicated step test.

Finds setpoint steps already present in AUTO data, fits a closed-loop FOPDT model on each,
cross-checks the models on the other windows (free-run R2) and grades the result. When no
usable step exists the answer is "no_excitation" with a bump-test recommendation: nothing
is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from crosscut_loops.history_windows import ExcitationWindow, find_excitation_windows
from crosscut_loops.identification_quality import free_run_r2
from crosscut_loops.tuning_report import (
    DEFAULT_ROBUSTNESS,
    TuningReport,
    identify_model,
    report_from_model,
)
from crosscut_loops.tuning_rules import FopdtModel

MAX_WINDOWS = 8  # only the largest setpoint steps are fitted
# Free-run R2 thresholds: a window model counts as good at HIGH_R2 on its own window;
# the mean R2 on the other windows must reach HIGH_R2 for "high", CROSS_R2 for "medium".
HIGH_R2, CROSS_R2 = 0.7, 0.5
# Largest ratio (max/min over the good models) of gain and time constant that still
# counts as agreeing ("high" confidence), and the looser limit for "medium".
CONSISTENT_GAIN_RATIO, CONSISTENT_TAU_RATIO = 1.3, 1.5
LOOSE_GAIN_RATIO, LOOSE_TAU_RATIO = 1.6, 2.5
CAUTIOUS_ROBUSTNESS = 0.7  # minimum robustness slider (0 fast .. 1 robust) below high confidence
CAUTIOUS_FACTOR = 1.5  # largest allowed change of Kc or Ti against the running settings


@dataclass(frozen=True)
class HistoryTuning:
    """Outcome of tuning from history.

    status: "ok", "low_confidence", "no_excitation" or "no_model".
    confidence: "high", "medium", "low" or "none". recommendation: "retune",
    "retune_cautiously" or "bump_test". max_change_factor: limit for medium confidence.
    """

    status: str
    confidence: str
    windows_found: int
    windows_used: int
    model: FopdtModel | None
    report: TuningReport | None
    cross_r2: float | None
    recommendation: str
    max_change_factor: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Fit:
    """One window's model and its free-run R2 on that same window."""

    window: ExcitationWindow
    model: FopdtModel
    own_r2: float


@dataclass(frozen=True)
class _Solution:
    """What the tuning found: the chosen model, its settings and the window counts."""

    model: FopdtModel | None = None
    report: TuningReport | None = None
    cross_r2: float | None = None
    windows_found: int = 0
    windows_used: int = 0


# codecheck: allow too-many-parameters (public signature used by experiments 17/26 and tests)
def tune_from_history(
    loop_name: str,
    sp: np.ndarray,
    op: np.ndarray,
    pv: np.ndarray,
    dt_s: float,
    robustness: float = DEFAULT_ROBUSTNESS,
) -> HistoryTuning:
    """Fit models on the natural setpoint steps of an AUTO record and grade them."""
    sp, op, pv = (np.asarray(series, dtype=float) for series in (sp, op, pv))
    windows = find_excitation_windows(sp, pv, dt_s)
    fits = _fit_windows(windows, op, pv, dt_s)
    if not fits:
        return _failure(windows)
    best, cross = _best_fit(fits, op, pv, dt_s)
    confidence, reasons = _grade(fits, best, cross)
    report = _settings_report(loop_name, best.model, confidence, robustness)
    status = "ok" if confidence in ("high", "medium") else "low_confidence"
    solution = _Solution(best.model, report, cross, len(windows), len(fits))
    return _result(status, confidence, reasons, solution)


def _failure(windows: list[ExcitationWindow]) -> HistoryTuning:
    """Result when no window gave a model: no step at all, or every fit failed."""
    if not windows:
        return _result("no_excitation", "none", ("no setpoint step in the data",), _Solution())
    no_model = _Solution(windows_found=len(windows))
    return _result("no_model", "none", ("no window gave a model",), no_model)


def _settings_report(
    loop_name: str, model: FopdtModel, confidence: str, robustness: float
) -> TuningReport | None:
    """Tuning settings for the chosen model, or None when the confidence is low."""
    robust = robustness if confidence == "high" else max(robustness, CAUTIOUS_ROBUSTNESS)
    # Low confidence gives no settings at all (exp26: some low-confidence level-loop fits
    # implied Ti 20-50 times too short); the model stays for diagnosis, the answer is a bump test.
    return None if confidence == "low" else report_from_model(loop_name, model, robust)


def cautious_step(current: float, proposed: float, factor: float = CAUTIOUS_FACTOR) -> float:
    """Clip ``proposed`` to the range [current / factor, current * factor]."""
    if current <= 0 or proposed <= 0:
        return proposed
    return float(min(max(proposed, current / factor), current * factor))


def _fit_windows(
    windows: list[ExcitationWindow], op: np.ndarray, pv: np.ndarray, dt_s: float
) -> list[_Fit]:
    """Closed-loop FOPDT fit of the largest windows; failing windows are skipped."""
    ranked = sorted(windows, key=lambda window: -abs(window.step_size))[:MAX_WINDOWS]
    fits = []
    for window in ranked:
        rows = slice(window.start, window.stop)
        model = identify_model(op[rows], pv[rows], dt_s)
        if model is None:
            continue
        fits.append(_Fit(window, model, free_run_r2(model, op[rows], pv[rows], dt_s)))
    return fits


def _best_fit(
    fits: list[_Fit], op: np.ndarray, pv: np.ndarray, dt_s: float
) -> tuple[_Fit, float | None]:
    """Fit with the best mean R2 on the other windows (own R2 when there is only one)."""
    if len(fits) == 1:
        return fits[0], None
    scored = []
    for fit in fits:
        others = [other for other in fits if other is not fit]
        r2_values = [
            free_run_r2(
                fit.model,
                op[other.window.start : other.window.stop],
                pv[other.window.start : other.window.stop],
                dt_s,
            )
            for other in others
        ]
        scored.append((float(np.mean(r2_values)), fit))
    cross, best = max(scored, key=lambda pair: pair[0])
    return best, cross


def _grade(fits: list[_Fit], best: _Fit, cross: float | None) -> tuple[str, tuple[str, ...]]:
    """High: agreeing models that predict each other; medium: looser; one window is low."""
    good = [fit for fit in fits if fit.own_r2 >= HIGH_R2]
    gains = [fit.model.gain for fit in good]
    taus = [fit.model.time_constant_s for fit in good]
    if len(good) >= 2 and cross is not None:
        tight = _ratio(gains) <= CONSISTENT_GAIN_RATIO and _ratio(taus) <= CONSISTENT_TAU_RATIO
        loose = _ratio(gains) <= LOOSE_GAIN_RATIO and _ratio(taus) <= LOOSE_TAU_RATIO
        if tight and cross >= HIGH_R2:
            return "high", ()
        if loose and cross >= CROSS_R2:
            return "medium", ("windows agree only loosely: apply in small steps",)
    reason = "a single window" if len(fits) == 1 else "windows disagree or fit poorly"
    return "low", (f"{reason}; best own R2 {best.own_r2:.2f}",)


def _ratio(values: list[float]) -> float:
    """Largest over smallest value (inf when empty or non-positive)."""
    return float(max(values) / min(values)) if values and min(values) > 0 else float("inf")


def _result(
    status: str, confidence: str, reasons: tuple[str, ...], solution: _Solution
) -> HistoryTuning:
    """Assemble the result with the matching recommendation."""
    recommendation = {"high": "retune", "medium": "retune_cautiously"}.get(confidence, "bump_test")
    factor = CAUTIOUS_FACTOR if confidence == "medium" else None
    return HistoryTuning(
        status,
        confidence,
        solution.windows_found,
        solution.windows_used,
        solution.model,
        solution.report,
        solution.cross_r2,
        recommendation,
        factor,
        reasons,
    )
