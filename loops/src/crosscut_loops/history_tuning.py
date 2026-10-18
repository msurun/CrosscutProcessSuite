"""Tune a loop from historian data without a dedicated step test.

Finds setpoint steps already present in AUTO data, fits a closed-loop FOPDT model on each,
cross-checks the models on the other windows and grades the result. When no usable step
exists the answer is "no_excitation" with a bump-test recommendation: nothing is guessed.
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

MAX_WINDOWS = 8
HIGH_R2, CROSS_R2 = 0.7, 0.5
CONSISTENT_GAIN_RATIO, CONSISTENT_TAU_RATIO = 1.3, 1.5
LOOSE_GAIN_RATIO, LOOSE_TAU_RATIO = 1.6, 2.5
CAUTIOUS_ROBUSTNESS = 0.7
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
    window: ExcitationWindow
    model: FopdtModel
    own_r2: float


def tune_from_history(
    loop_name: str,
    sp: np.ndarray,
    op: np.ndarray,
    pv: np.ndarray,
    dt_s: float,
    robustness: float = DEFAULT_ROBUSTNESS,
) -> HistoryTuning:
    """Fit models on the natural setpoint steps of an AUTO record and grade them."""
    sp, op, pv = (np.asarray(x, dtype=float) for x in (sp, op, pv))
    windows = find_excitation_windows(sp, pv, dt_s)
    if not windows:
        return _result("no_excitation", "none", 0, 0, None, None, ("no setpoint step in the data",))
    fits = _fit_windows(windows, sp, op, pv, dt_s)
    if not fits:
        return _result("no_model", "none", len(windows), 0, None, None, ("no window gave a model",))
    best, cross = _best_fit(fits, op, pv, dt_s)
    confidence, reasons = _grade(fits, best, cross)
    robust = robustness if confidence == "high" else max(robustness, CAUTIOUS_ROBUSTNESS)
    report = report_from_model(loop_name, best.model, robust)
    return _result(
        "ok" if confidence in ("high", "medium") else "low_confidence",
        confidence,
        len(windows),
        len(fits),
        best.model,
        report,
        reasons,
        cross,
    )


def cautious_step(current: float, proposed: float, factor: float = CAUTIOUS_FACTOR) -> float:
    """Clip ``proposed`` to within ``factor`` times / over ``factor`` of ``current``."""
    if current <= 0 or proposed <= 0:
        return proposed
    return float(min(max(proposed, current / factor), current * factor))


def _fit_windows(
    windows: list[ExcitationWindow], sp: np.ndarray, op: np.ndarray, pv: np.ndarray, dt_s: float
) -> list[_Fit]:
    """Closed-loop FOPDT fit of the largest windows; failing windows are skipped."""
    ranked = sorted(windows, key=lambda w: -abs(w.step_size))[:MAX_WINDOWS]
    fits = []
    for w in ranked:
        s = slice(w.start, w.stop)
        model = identify_model(op[s], pv[s], dt_s)
        if model is None:
            continue
        fits.append(_Fit(w, model, free_run_r2(model, op[s], pv[s], dt_s)))
    return fits


def _best_fit(
    fits: list[_Fit], op: np.ndarray, pv: np.ndarray, dt_s: float
) -> tuple[_Fit, float | None]:
    """Fit with the best mean R2 on the other windows (own R2 when there is only one)."""
    if len(fits) == 1:
        return fits[0], None
    scored = []
    for f in fits:
        others = [g for g in fits if g is not f]
        r2 = [
            free_run_r2(
                f.model,
                op[g.window.start : g.window.stop],
                pv[g.window.start : g.window.stop],
                dt_s,
            )
            for g in others
        ]
        scored.append((float(np.mean(r2)), f))
    cross, best = max(scored, key=lambda t: t[0])
    return best, cross


def _grade(fits: list[_Fit], best: _Fit, cross: float | None) -> tuple[str, tuple[str, ...]]:
    """High: agreeing models that predict each other; medium: looser; one window is low."""
    good = [f for f in fits if f.own_r2 >= HIGH_R2]
    gains = [f.model.gain for f in good]
    taus = [f.model.time_constant_s for f in good]
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
    status: str,
    confidence: str,
    found: int,
    used: int,
    model: FopdtModel | None,
    report: TuningReport | None,
    reasons: tuple[str, ...],
    cross: float | None = None,
) -> HistoryTuning:
    """Assemble the result with the matching recommendation."""
    recommendation = {"high": "retune", "medium": "retune_cautiously"}.get(confidence, "bump_test")
    factor = CAUTIOUS_FACTOR if confidence == "medium" else None
    return HistoryTuning(
        status, confidence, found, used, model, report, cross, recommendation, factor, reasons
    )
