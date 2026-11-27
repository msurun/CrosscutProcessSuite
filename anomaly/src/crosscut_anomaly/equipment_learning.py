"""Learn explainable normal-operation models for catalogue equipment.

Only uninterrupted running, automatic, unsaturated samples train PCA and load residuals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from crosscut_anomaly.pca_model import PcaModel, fit_pca

QUIET_SAMPLES = 30  # Samples in the shortest uninterrupted usable stretch.
ROWS_PER_VARIABLE = 10  # Rows per PCA column, including lagged copies.
MIN_PCA_ROWS = 50  # Samples required by the shared PCA fitter.
SATURATION_MARGIN = 0.02  # Fraction of the configured OUT engineering span.
EWMA_WEIGHT = 0.2  # Dimensionless weight of the newest standardised residual.
EWMA_LIMIT = 3.0  # Standardised residual units, two-sided.
RESIDUAL_FLOOR = 1e-12  # Signal engineering units; guards exact synthetic fits.
CONDITION_KINDS = {"current", "power", "temperature", "vibration"}
LOOP_ROLES = ("pv", "sp", "out")
STOPPED_MODE = "stopped"  # mode label (crosscut_connectors.mode_eval): never learned or scored
IGNORED_MODES = {STOPPED_MODE, "unknown", "none"}  # labels that get no model of their own
MIN_MODE_SAMPLES = 200  # usable samples a mode needs before it gets limits of its own
MODE_LIMITS = "mode"  # limits learned on this mode alone
ALL_RUNNING_LIMITS = "all_running"  # fallback: limits of all running samples, flagged
MANUAL_MODE = 0  # MODE code in crosscut_loops.loop_modes; every other finite code is active.


def _owned_loops(equipment: dict, loops: list[dict]) -> list[dict]:
    """Select primary ownership in catalogue order, refusing dangling references."""
    missing = set(equipment.get("loops", [])) - {loop["id"] for loop in loops}
    if missing:
        raise ValueError(f"Unknown owned loops {sorted(missing)}; repair the catalogue")
    return [loop for loop in loops if loop["id"] in equipment.get("loops", [])]


def _variables(equipment: dict, loops: list[dict]) -> list[str]:
    """Collect ordered unique measurement and contextual tag ids."""
    tags = [loop[role] for loop in _owned_loops(equipment, loops)
            for role in LOOP_ROLES if role in loop]
    tags.extend(signal["tag"] for signal in equipment.get("signals", []))
    return list(dict.fromkeys(tags))


def equipment_variables(site: dict, equipment_id: str) -> list[str]:
    """Return owned loop and condition variables; raise ValueError for an unknown id."""
    equipment = next((item for item in site.get("equipment", [])
                      if item["id"] == equipment_id), None)
    if equipment is None:
        raise ValueError(f"Unknown equipment {equipment_id!r}; select a catalogue equipment id")
    return _variables(equipment, site.get("loops", []))


def _times(t_s: Any) -> np.ndarray:
    """Validate strictly increasing finite sample times in seconds."""
    times = np.asarray(t_s, dtype=float)
    if times.ndim != 1 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("t_s must contain finite increasing seconds; sort and deduplicate samples")
    return times


def _column(data: dict, tag: str, count: int) -> np.ndarray:
    """Read one aligned numeric channel, with an actionable error for missing input."""
    if tag not in data:
        raise ValueError(f"Missing tag {tag!r}; include it in the dataset")
    values = np.asarray(data[tag], dtype=float)
    if values.shape != (count,):
        raise ValueError(f"Tag {tag!r} must contain {count} aligned samples")
    return values


def _spans(times: np.ndarray, mask: np.ndarray) -> list[np.ndarray]:
    """Split usable indices at rejected samples and archive gaps."""
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    # A gap above 1.5 nominal periods breaks continuity, as in the PCA scan engine.
    period_s = float(np.median(np.diff(times))) if len(times) > 1 else 1.0
    breaks = (np.diff(indices) != 1) | (np.diff(times[indices]) > 1.5 * period_s)
    return list(np.split(indices, np.flatnonzero(breaks) + 1))


def _loop_rules(data: dict, loop: dict, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Return manual and saturated flags using the loop monitor's mode convention."""
    # Missing mode evidence cannot establish automatic operation. CAS/RSP, like AUTO,
    # are active in monitor.py; MAN is zero. Nonfinite modes provide no evidence.
    mode = _column(data, loop["mode"], count) if "mode" in loop else np.full(count, np.nan)
    output = _column(data, loop["out"], count)
    limits = loop.get("out_limits", {})
    low = loop.get("out_eng_min", limits.get("low", 0.0))
    high = loop.get("out_eng_max", limits.get("high", 100.0))
    if not np.isfinite([low, high]).all() or high <= low:
        raise ValueError(f"Loop {loop['id']}: configure increasing finite OUT limits")
    fraction = (output - low) / (high - low)
    saturated = ~np.isfinite(output) | (fraction < SATURATION_MARGIN)
    saturated |= fraction > 1 - SATURATION_MARGIN
    return ~np.isfinite(mode) | (mode == MANUAL_MODE), saturated


def training_mask(
    t_s: Any, data: dict, equipment: dict, loops: list[dict], labels: Any = None,
) -> tuple:
    """Return usability and exclusive counts removed by running, mode, OUT and quiet rules.

    ``labels`` (optional) holds the operating-mode label of every sample; samples in mode
    ``stopped`` count as stopped like a false running signal.
    """
    times = _times(t_s)
    mask = np.ones(len(times), dtype=bool)
    running = equipment.get("running")
    stopped = np.zeros(len(times), dtype=bool)
    if running:
        values = _column(data, running["tag"], len(times))
        stopped = ~np.isfinite(values) | (values <= running["above"])
    if labels is not None:
        stopped |= np.asarray(labels, dtype=object) == STOPPED_MODE
    manual, saturated = np.zeros_like(mask), np.zeros_like(mask)
    for loop in _owned_loops(equipment, loops):
        loop_manual, loop_saturated = _loop_rules(data, loop, len(times))
        manual |= loop_manual
        saturated |= loop_saturated
    reasons = {}
    for name, rejected in (("stopped", stopped), ("manual", manual), ("saturated", saturated)):
        reasons[name] = int(np.count_nonzero(mask & rejected))
        mask &= ~rejected
    quiet = _quiet_mask(times, mask)
    reasons["quiet"] = int(np.count_nonzero(mask & ~quiet))
    return quiet, reasons


def _quiet_mask(times: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Keep complete eligible stretches of thirty samples, without variance heuristics."""
    quiet = np.zeros(len(times), dtype=bool)
    for span in _spans(times, mask):
        if len(span) >= QUIET_SAMPLES:
            quiet[span] = True
    return quiet


def propose_windows(t_s: Any, mask: Any, min_len_s: float) -> list[list[float]]:
    """Return closed usable spans whose elapsed duration meets the seconds threshold."""
    times = _times(t_s)
    usable = np.asarray(mask, dtype=bool)
    if usable.shape != times.shape or not np.isfinite(min_len_s) or min_len_s < 0:
        raise ValueError("Provide an aligned mask and a finite nonnegative minimum duration")
    return [[float(times[span[0]]), float(times[span[-1]])]
            for span in _spans(times, usable)
            if times[span[-1]] - times[span[0]] >= min_len_s]


def _intervals(windows: Any) -> list[list[float]]:
    """Validate finite ordered closed intervals in seconds."""
    result = []
    for window in windows:
        if len(window) != 2 or not np.isfinite(window).all() or window[0] > window[1]:
            raise ValueError("Windows must be finite [start_s, end_s] with start_s <= end_s")
        result.append([float(window[0]), float(window[1])])
    return result


def apply_exclusions(windows: Any, exclusions: Any) -> list[list[float]]:
    """Subtract closed excluded intervals, preserving the order of remaining spans."""
    remaining = _intervals(windows)
    for start, end in _intervals(exclusions):
        remaining = _subtract_interval(remaining, start, end)
    return remaining


def _subtract_interval(windows: list, start: float, end: float) -> list[list[float]]:
    """Use adjacent representable seconds to exclude both boundary samples."""
    remaining = []
    for low, high in windows:
        if high < start or low > end:
            remaining.append([low, high])
            continue
        if low < start:
            remaining.append([low, float(np.nextafter(start, -np.inf))])
        if high > end:
            remaining.append([float(np.nextafter(end, np.inf)), high])
    return remaining


@dataclass
class EquipmentModel:
    """JSON-persistable fitted equipment model and sequential scoring state."""

    status: str
    variables: list[str]
    windows: list[list[float]]
    reasons: dict[str, int]
    pca: PcaModel | None = None
    by_mode: dict[str, EquipmentModel] = field(default_factory=dict)
    mode_limits: dict[str, str] = field(default_factory=dict)
    per_loop: dict[str, PcaModel] = field(default_factory=dict)
    regressions: dict[str, dict] = field(default_factory=dict)
    previous: list[float] | None = None
    ewma: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible coefficients, training evidence and scoring state."""
        return {"status": self.status, "variables": self.variables, "windows": self.windows,
                "reasons": self.reasons, "pca": self.pca.to_dict() if self.pca else None,
                "fallback": "per_loop" if self.status == "not_enough_data" else None,
                "per_loop": {name: model.to_dict() for name, model in self.per_loop.items()},
                "regressions": self.regressions, "previous": self.previous, "ewma": self.ewma,
                "by_mode": {mode: sub.to_dict() for mode, sub in self.by_mode.items()},
                "mode_limits": self.mode_limits}

    def for_mode(self, mode: str | None) -> tuple[EquipmentModel, str]:
        """The model that scores samples of ``mode`` and the limits flag of that choice.

        A mode with its own model gives ``mode``; any other mode (or none) falls back to the
        all-running model and is flagged ``all_running`` so the console can show it.
        """
        if mode in self.by_mode:
            return self.by_mode[mode], MODE_LIMITS
        return self, ALL_RUNNING_LIMITS

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> EquipmentModel:
        """Restore a saved model, rejecting unknown training states."""
        if document.get("status") not in {"learned", "learning", "not_enough_data"}:
            raise ValueError("Unknown equipment model status; retrain the model")
        model = cls(document["status"], document["variables"], document["windows"],
                    document["reasons"])
        model.pca = PcaModel.from_dict(document["pca"]) if document.get("pca") else None
        model.per_loop = {name: PcaModel.from_dict(saved)
                          for name, saved in document.get("per_loop", {}).items()}
        model.regressions = document.get("regressions", {})
        model.previous, model.ewma = document.get("previous"), document.get("ewma", {})
        model.by_mode = {mode: cls.from_dict(saved)
                         for mode, saved in document.get("by_mode", {}).items()}
        model.mode_limits = document.get("mode_limits", {})
        return model


def _fit_if_possible(rows: np.ndarray, tags: list[str], lags: int) -> PcaModel | None:
    """Return no model when the shared fitter's sample or movement gate is unmet."""
    from crosscut_anomaly.pca_model import augment_lags

    augmented = augment_lags(rows, lags)
    valid = augmented[np.isfinite(augmented).all(axis=1)]
    minimum = max(MIN_PCA_ROWS, ROWS_PER_VARIABLE * len(tags) * (lags + 1))
    if len(tags) < 2 or len(valid) < minimum or not np.any(np.ptp(valid, axis=0)):
        return None
    return fit_pca(rows, tags, dynamic_lags=lags, allow_constants=True)


def _selected_rows(times: np.ndarray, data: dict, tags: list[str], mask: np.ndarray) -> tuple:
    """Reject missing measurements before enforcing uninterrupted quiet stretches."""
    rows = np.column_stack([_column(data, tag, len(times)) for tag in tags])
    finite = np.isfinite(rows).all(axis=1)
    selected = _quiet_mask(times, mask & finite)
    # NaNs preserve the original index: lag one must never jump across a rejected row.
    return np.where(selected[:, None], rows, np.nan), selected


def _exclude_samples(times: np.ndarray, mask: np.ndarray, exclusions: Any) -> np.ndarray:
    """Apply closed user exclusions before rebuilding quiet stretches and lag history."""
    selected = mask.copy()
    for start, end in _intervals(exclusions):
        selected &= ~((times >= start) & (times <= end))
    return _quiet_mask(times, selected)


def learn_equipment(
    t_s: Any, data: dict, equipment: dict, loops: list[dict], exclusions: Any = (),
    labels: Any = None,
) -> EquipmentModel:
    """Fit lagged equipment PCA and conditional residuals, or explicit per-loop fallback.

    ``labels`` (operating-mode label per sample, optional) leaves stopped samples out and also
    fits a model per mode that has enough usable samples; the other modes are flagged to use the
    all-running model (``mode_limits``).
    """
    model = _fit_model(t_s, data, equipment, loops, (exclusions, labels, None))
    if labels is None:
        return model
    names = {str(x) for x in labels} - IGNORED_MODES
    for name in sorted(names):
        sub = _fit_model(t_s, data, equipment, loops, (exclusions, labels, name))
        usable = sub.status == "learned" or bool(sub.regressions)
        if usable and sub.reasons["used"] >= MIN_MODE_SAMPLES:
            model.by_mode[name] = sub
        model.mode_limits[name] = MODE_LIMITS if name in model.by_mode else ALL_RUNNING_LIMITS
    return model


def _fit_model(
    t_s: Any, data: dict, equipment: dict, loops: list[dict], scope: tuple,
) -> EquipmentModel:
    """Fit one model on the running samples, optionally only those of one operating mode."""
    exclusions, labels, only = scope
    times = _times(t_s)
    tags = _variables(equipment, loops)
    mask, reasons = training_mask(times, data, equipment, loops, labels)
    if only is not None:
        mask &= np.asarray(labels, dtype=object) == only
    selected = _exclude_samples(times, mask, exclusions)
    reasons = {**reasons, "excluded": int(np.count_nonzero(mask & ~selected)),
               "used": int(np.count_nonzero(selected))}
    if not tags:
        return EquipmentModel("not_enough_data", [], [], reasons)
    rows, selected = _selected_rows(times, data, tags, selected)
    model = EquipmentModel("not_enough_data", tags, propose_windows(times, selected, 0), reasons)
    model.pca = _fit_if_possible(_break_archive_gaps(times, rows), tags, 1)
    if model.pca is not None:
        model.status = "learned"
    else:
        model.per_loop = _fallback_models((times, data), equipment, loops, scope)
    model.regressions = _fit_regressions(data, equipment, loops, selected)
    return model


def _break_archive_gaps(times: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Insert missing history between archive segments before fitting lagged PCA."""
    if len(times) < 2:
        return rows
    period_s = float(np.median(np.diff(times)))
    boundaries = np.flatnonzero(np.diff(times) > 1.5 * period_s) + 1
    return np.insert(rows, boundaries, np.nan, axis=0)


def _fallback_models(record: tuple, equipment: dict, loops: list, scope: tuple) -> dict:
    """Fit each loop independently; running, stopped mode and user exclusions still apply."""
    times, data = record
    exclusions, labels, only = scope
    result = {}
    for loop in _owned_loops(equipment, loops):
        local = {**equipment, "loops": [loop["id"]]}
        mask, _ = training_mask(times, data, local, loops, labels)
        if only is not None:
            mask &= np.asarray(labels, dtype=object) == only
        mask = _exclude_samples(times, mask, exclusions)
        tags = [loop[role] for role in LOOP_ROLES if role in loop]
        rows, _ = _selected_rows(times, data, tags, mask)
        fitted = _fit_if_possible(rows, tags, 0)
        if fitted is not None:
            result[loop["id"]] = fitted
    return result


def _design(outputs: np.ndarray, power: bool) -> np.ndarray:
    """Build intercept, OUT and optional cubic OUT predictors in engineering units."""
    # Least squares: signal = intercept + sum(b_j OUT_j) + sum(c_j OUT_j^3).
    # Pump affinity P ~ n^3 motivates cubics only when OUT represents drive speed;
    # this is a catalogue proxy, not a claim of a measured physical speed model.
    predictors = [np.ones(len(outputs)), *outputs.T]
    if power:
        predictors.extend((outputs ** 3).T)
    return np.column_stack(predictors)


def _fit_regressions(data: dict, equipment: dict, loops: list, selected: np.ndarray) -> dict:
    """Fit load-dependent condition expectations on the same accepted training rows."""
    outputs = [loop["out"] for loop in _owned_loops(equipment, loops)]
    if not outputs or not selected.any():
        return {}
    operating = np.column_stack([data[tag] for tag in outputs])[selected]
    result = {}
    for signal in equipment.get("signals", []):
        if signal["kind"] in CONDITION_KINDS:
            design = _design(operating, signal["kind"] == "power")
            target = np.asarray(data[signal["tag"]], dtype=float)[selected]
            regression = _regression(design, target)
            if regression:
                result[signal["tag"]] = {**regression, "outputs": outputs,
                                        "power": signal["kind"] == "power"}
    return result


def _regression(design: np.ndarray, target: np.ndarray) -> dict:
    """Estimate coefficients and residual standard deviation in signal engineering units."""
    coefficients, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if len(target) < ROWS_PER_VARIABLE * design.shape[1] or len(target) <= rank:
        return {}
    residual = target - design @ coefficients
    # Regression residual variance is SSE / (n - rank), accounting for fitted parameters.
    deviation = float(np.sqrt(np.sum(residual ** 2) / (len(target) - rank)))
    return {"coefficients": coefficients.tolist(), "residual_std": max(deviation, RESIDUAL_FLOOR)}


def _score_residuals(model: EquipmentModel, row: dict) -> dict[str, float]:
    """Return z = (observed - expected) / training residual standard deviation."""
    result = {}
    for tag, regression in model.regressions.items():
        outputs = np.array([[row[name] for name in regression["outputs"]]])
        expected = float((_design(outputs, regression["power"])
                          @ np.asarray(regression["coefficients"]))[0])
        result[tag] = float((row[tag] - expected) / regression["residual_std"])
    return result


def score(model: EquipmentModel, x_row: Any) -> dict[str, Any]:
    """Score one chronological sample and update lag history and residual EWMA in place.

    The first sample has no lag history and returns null PCA statistics; residuals still score.
    """
    row = x_row if isinstance(x_row, dict) else dict(zip(model.variables, x_row, strict=True))
    values = np.asarray([row[tag] for tag in model.variables], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Scoring needs finite values for every model variable")
    result = _score_pca(model, values)
    residuals = _score_residuals(model, row)
    # EWMA_t = lambda*z_t + (1-lambda)*EWMA_(t-1), initialized at normal residual zero.
    # Both z and EWMA are dimensionless; use the requested fixed +/-3 z-unit limit.
    for tag, value in residuals.items():
        model.ewma[tag] = EWMA_WEIGHT * value + (1 - EWMA_WEIGHT) * model.ewma.get(tag, 0.0)
    model.previous = values.tolist()
    return {**result, "residuals": residuals, "ewma": dict(model.ewma), "ewma_limit": EWMA_LIMIT}


def _score_pca(model: EquipmentModel, values: np.ndarray) -> dict:
    """Score lagged PCA only when a real previous sample has been supplied."""
    if model.pca is None or model.previous is None:
        return {"t2": None, "spe": None, "contributions": {}}
    augmented = np.concatenate((values, model.previous))
    return {"t2": float(model.pca.t2(augmented)[0]),
            "spe": float(model.pca.spe(augmented)[0]),
            "contributions": model.pca.contributions(augmented)}
