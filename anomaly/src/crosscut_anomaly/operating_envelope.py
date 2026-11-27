"""Descriptive operating envelope per operating mode (PRODUCT 8.3a, #189).

Bins one or two operating variables and reports, per mode, the observed conditional quantiles
(p10/p50/p90) of an outcome tag in each bin with its sample count and time coverage. It is a
description of the data window only: no causal claim and no recommendation to change a setpoint.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

QUANTILES = (10, 50, 90)  # percent; numpy linear interpolation (Hyndman and Fan type 7)
OK = "ok"
INSUFFICIENT = "insufficient_data"
DIRECTIONS = ("max", "min")
METHOD = ("Observed conditional quantiles of the outcome in equal-width bins of the operating "
          "variables, per mode; stopped samples excluded; descriptive only.")


class EnvelopeError(ValueError):
    """The request cannot be answered from the data (unknown tag, bad option, no samples)."""


def _edges(values: np.ndarray, bins: int) -> np.ndarray:
    """``bins + 1`` equal-width edges over the finite range of ``values`` (shape (n,))."""
    low, high = float(np.min(values)), float(np.max(values))
    if high <= low:
        high = low + 1.0  # constant variable: one populated bin, the rest empty
    return np.linspace(low, high, bins + 1)


def _bin_index(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Bin number 0..bins-1 of each value; the top edge belongs to the last bin."""
    return np.clip(np.searchsorted(edges, values, side="right") - 1, 0, len(edges) - 2)


def _cell(outcome: np.ndarray, mode_total: int, period_s: float, min_count: int) -> dict[str, Any]:
    """Quantiles, count and coverage of one bin; quantiles are None below ``min_count``."""
    count = len(outcome)
    cell: dict[str, Any] = {"count": count, "duration_s": count * period_s,
                            "coverage": count / mode_total if mode_total else 0.0,
                            "status": OK if count >= min_count and count > 0 else INSUFFICIENT,
                            "p10": None, "p50": None, "p90": None, "best": False}
    if cell["status"] == OK:
        low, mid, high = np.percentile(outcome, QUANTILES)
        cell.update(p10=float(low), p50=float(mid), p90=float(high))
    return cell


def _mark_best(cells: list[dict[str, Any]], direction: str, tolerance: float) -> None:
    """Flag the bins whose median is within ``tolerance`` (outcome units) of the best median."""
    medians = [c["p50"] for c in cells if c["status"] == OK]
    if not medians:
        return
    best = max(medians) if direction == "max" else min(medians)
    for cell in cells:
        if cell["status"] == OK and abs(cell["p50"] - best) <= tolerance:
            cell["best"] = True


def _mode_cells(outcome: np.ndarray, cell_ids: np.ndarray, shape: Sequence[int],
                period_s: float, min_count: int) -> list[dict[str, Any]]:
    """One cell per bin of the grid (row-major over the variables), empty bins included."""
    cells = []
    for flat in range(int(np.prod(shape))):
        cell = _cell(outcome[cell_ids == flat], len(outcome), period_s, min_count)
        cell["index"] = [int(i) for i in np.unravel_index(flat, shape)]
        cells.append(cell)
    return cells


def _validate(variables: Sequence[str], direction: str, bins: int, min_count: int,
              tolerance: float) -> None:
    """Reject options outside the supported ranges before any data is touched."""
    if not 1 <= len(variables) <= 2:
        raise EnvelopeError("choose one or two operating variables")
    if direction not in DIRECTIONS or bins < 2 or min_count < 1 or tolerance < 0:
        raise EnvelopeError("direction must be max or min; bins >= 2, min_count >= 1, "
                            "tolerance >= 0")


def _columns(data: Mapping[str, Any], tags: Sequence[str]) -> list[np.ndarray]:
    """Float columns of the tags; a missing tag is an error naming it."""
    missing = [tag for tag in tags if tag not in data]
    if missing:
        raise EnvelopeError(f"unknown tag: {', '.join(missing)}")
    return [np.asarray(data[tag], dtype=float) for tag in tags]


def operating_envelope(
    data: Mapping[str, Any], labels: Sequence[str], stopped: np.ndarray, *, outcome: str,
    variables: Sequence[str], sample_period_s: float, bins: int = 8, min_count: int = 20,
    tolerance: float = 0.0, direction: str = "max",
) -> dict[str, Any]:
    """Per-mode binned quantiles of ``outcome`` (data: tag -> array of n samples).

    ``labels`` is the mode of each sample (``unknown`` samples are dropped), ``stopped`` is a
    boolean mask of samples to exclude. Bin edges are shared by all modes so cells compare.
    """
    _validate(variables, direction, bins, min_count, tolerance)
    y, *xs = _columns(data, [outcome, *variables])
    modes = np.asarray(labels, dtype=object)
    off = np.asarray(stopped, bool)
    usable = ~off & (modes != "unknown") & np.isfinite(y)
    for x in xs:
        usable &= np.isfinite(x)
    if not usable.any():
        raise EnvelopeError("no running samples with finite values in this window")
    grid = [_edges(x[usable], bins) for x in xs]
    ids = np.zeros(len(y), dtype=int)
    for x, edges in zip(xs, grid, strict=True):
        ids = ids * bins + _bin_index(x, edges)
    result: dict[str, Any] = {}
    for mode in dict.fromkeys(modes[usable]):
        pick = usable & (modes == mode)
        cells = _mode_cells(y[pick], ids[pick], [bins] * len(xs), sample_period_s, min_count)
        _mark_best(cells, direction, tolerance)
        result[str(mode)] = {"samples": int(pick.sum()), "cells": cells}
    return {"method": METHOD, "outcome": outcome, "variables": list(variables),
            "direction": direction, "tolerance": tolerance, "min_count": min_count,
            "edges": [[float(v) for v in edge] for edge in grid], "modes": result,
            "excluded_stopped": int(off.sum()), "samples": int(len(y)),
            "sample_period_s": sample_period_s}
