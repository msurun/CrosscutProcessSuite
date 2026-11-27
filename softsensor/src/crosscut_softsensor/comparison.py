"""Compare preset structures with causal laboratory baselines on blocked folds.

Every method is scored on identical held-out samples, in the target engineering unit.
Labels enter training or baseline state only after their recorded release time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_softsensor.deployment_gate import GateDecision, ValidationResults, evaluate_gate
from crosscut_softsensor.pls import cv_split
from crosscut_softsensor.runner import LabResults

EWMA_WEIGHT = 0.2  # Dimensionless, frozen baseline smoothing weight.
MIN_TRAINING_ROWS = 3


@dataclass(frozen=True)
class ComparisonData:
    """Process X (rows, roles), strictly increasing seconds, and released lab labels.

    Feature names identify columns and their preset engineering units. X must already
    contain causal lag/window features; a lab sample uses the nearest earlier process row.
    """

    x: np.ndarray
    t_s: np.ndarray
    labs: LabResults
    feature_names: tuple[str, ...]


@dataclass(frozen=True)
class ComparisonOptions:
    """Fold count, gap in process rows, maximum feature lag, and lab-age limit in seconds."""

    n_blocks: int = 4
    gap: int = 0
    max_lag: int = 0
    max_lab_age_s: float = float("inf")


DEFAULT_OPTIONS = ComparisonOptions()


@dataclass(frozen=True)
class ComparisonTable:
    """Common-row metrics, baseline ages (seconds), and gate decisions per structure."""

    rows: tuple[dict[str, Any], ...]
    decisions: dict[str, GateDecision]
    predictions: dict[str, np.ndarray]
    lab_age_s: np.ndarray
    scored_mask: np.ndarray


def _validate_data(data: ComparisonData, options: ComparisonOptions) -> np.ndarray:
    """Validate aligned finite timestamps and return process positions for lab samples."""
    times, labs = np.asarray(data.t_s), data.labs
    if times.ndim != 1 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Process times must be finite and strictly increasing seconds")
    if data.x.shape != (len(times), len(data.feature_names)):
        raise ValueError("X must have one row per timestamp and one column per feature name")
    if labs.t_s.ndim != 1 or labs.values.shape != labs.t_s.shape:
        raise ValueError("Lab sample times and values must be equally sized vectors")
    if labs.available_s.shape != labs.t_s.shape or not np.isfinite(labs.available_s).all():
        raise ValueError("Supply a finite release time for each lab sample")
    if np.any(np.diff(labs.t_s) <= 0) or not np.isfinite(labs.t_s).all():
        raise ValueError("Lab sample times must be finite and strictly increasing")
    if np.any(labs.available_s < labs.t_s) or not options.max_lab_age_s >= 0:
        raise ValueError("Lab release cannot precede sampling; maximum age must be nonnegative")
    positions = np.searchsorted(times, labs.t_s, side="right") - 1
    if np.any(positions < 0) or np.any(labs.t_s > times[-1]):
        raise ValueError("Lab sample times must lie within the process record")
    return positions


def delayed_baselines(
    cutoff_s: np.ndarray, labs: LabResults, max_age_s: float = float("inf")
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Persistence, EWMA and age using only earlier samples released by each cutoff.

    Age is cutoff minus the latest known sample time, not time since release. Reordered
    releases update EWMA in release order; persistence retains the most recent sample.
    """
    persistence = np.full(len(cutoff_s), np.nan)
    smoothed, ages = persistence.copy(), persistence.copy()
    release_order = np.argsort(labs.available_s, kind="stable")
    for index, cutoff in enumerate(cutoff_s):
        known = release_order[(labs.available_s[release_order] <= cutoff)
                              & (labs.t_s[release_order] < cutoff)
                              & np.isfinite(labs.values[release_order])]
        if not len(known):
            continue
        latest = known[np.argmax(labs.t_s[known])]
        ages[index] = cutoff - labs.t_s[latest]
        if ages[index] <= max_age_s:
            persistence[index] = labs.values[latest]
            smoothed[index] = _ewma(labs.values[known])
    return persistence, smoothed, ages


def _ewma(values: np.ndarray) -> float:
    """Return release-order EWMA in target units, initialised with the first known value."""
    state = float(values[0])
    for value in values[1:]:
        state += EWMA_WEIGHT * (float(value) - state)
    return state


def compare_preset(
    preset: dict[str, Any], data: ComparisonData, options: ComparisonOptions = DEFAULT_OPTIONS
) -> ComparisonTable:
    """Fit allowed structures on forward blocks and evaluate their deployment gates.

    The initial block is training only. Each later block is predicted once with a frozen
    fit; causal baseline updates may consume earlier labels released within that block.
    """
    if min(options.gap, options.max_lag) < 0:
        raise ValueError("Gap and maximum lag must be nonnegative process row counts")
    positions = _validate_data(data, options)
    gap = max(options.gap, options.max_lag)
    splits = cv_split(positions, options.n_blocks, gap, forward_only=True)
    names = tuple(preset["model"]["allowed_now"])
    predictions = {name: np.full(len(positions), np.nan) for name in ("mean", *names)}
    eligible = np.zeros(len(positions), dtype=bool)
    for train, validation in splits:
        eligible[validation] = True
        _predict_fold(preset, data, (positions, train, validation), predictions)
    baseline = preset["deployment_gate"]["baseline"]
    predictions[baseline], predictions["delayed_lab_ewma"], ages = delayed_baselines(
        data.labs.t_s, data.labs, options.max_lab_age_s
    )
    return _summarise(preset, data.labs.values, predictions, (eligible, ages))


def _predict_fold(
    preset: dict[str, Any], data: ComparisonData,
    indices: tuple[np.ndarray, np.ndarray, np.ndarray], predictions: dict[str, np.ndarray],
) -> None:
    """Train on finite features and labels released before the earliest held-out cutoff."""
    from crosscut_softsensor.preset_structures import create_structure

    positions, train, validation = indices
    features = data.x[positions]
    known = data.labs.available_s[train] <= data.labs.t_s[validation[0]]
    finite = np.isfinite(features[train]).all(axis=1) & np.isfinite(data.labs.values[train])
    train = train[known & finite]
    if len(train) < MIN_TRAINING_ROWS:
        return  # Missing evidence remains unscored and reduces reported coverage.
    predictions["mean"][validation] = np.mean(data.labs.values[train])
    usable = validation[np.isfinite(features[validation]).all(axis=1)]
    for name in preset["model"]["allowed_now"]:
        model = create_structure(preset, name, data.feature_names)
        model.fit(features[train], data.labs.values[train])
        if len(usable):
            predictions[name][usable] = model.predict(features[usable])


def _metrics(truth: np.ndarray, prediction: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    """RMSE and MAE in target units; no scored evidence produces NaN, never zero error."""
    residual = prediction[mask] - truth[mask]
    return {"rmse": float(np.sqrt(np.mean(residual**2))) if len(residual) else float("nan"),
            "mae": float(np.mean(np.abs(residual))) if len(residual) else float("nan"),
            "n": int(mask.sum())}


def _summarise(
    preset: dict[str, Any], truth: np.ndarray, predictions: dict[str, np.ndarray],
    population: tuple[np.ndarray, np.ndarray],
) -> ComparisonTable:
    """Compare every method on the intersection and gate against the strongest baseline."""
    eligible, ages = population
    mask = eligible & np.isfinite(truth)
    for prediction in predictions.values():
        mask &= np.isfinite(prediction)
    coverage = float(mask.sum() / eligible.sum()) if eligible.any() else 0.0
    rows = {name: {"method": name, **_metrics(truth, values, mask), "coverage": coverage}
            for name, values in predictions.items()}
    baselines = ("mean", preset["deployment_gate"]["baseline"], "delayed_lab_ewma")
    strongest = min(baselines, key=lambda name: rows[name]["rmse"])
    reference = rows[strongest]["rmse"]
    decisions = _gate_rows(preset, rows, (strongest, reference, coverage))
    return ComparisonTable(tuple(rows.values()), decisions, predictions, ages, mask)


def _gate_rows(
    preset: dict[str, Any], rows: dict[str, dict[str, Any]], reference: tuple[str, float, float]
) -> dict[str, GateDecision]:
    """Attach skills and supply the strongest error under the preset's baseline contract."""
    strongest, baseline_rmse, coverage = reference
    decisions = {}
    for name, row in rows.items():
        row["strongest_baseline"] = strongest
        row["skill"] = 1 - row["rmse"] / baseline_rmse if baseline_rmse > 0 else None
        if name in preset["model"]["allowed_now"]:
            results = ValidationResults(row["rmse"], baseline_rmse, coverage, row["n"],
                                        preset["deployment_gate"]["baseline"])
            decisions[name] = evaluate_gate(preset["deployment_gate"], results)
    return decisions
