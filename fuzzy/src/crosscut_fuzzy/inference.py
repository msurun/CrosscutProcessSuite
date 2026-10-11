"""Mamdani inference: membership degrees, rule firing, aggregation and centroid defuzzification.

All functions work on arrays of samples (a single sample is an array of length one), so the same
code serves the live what-if panel and the replay over a recorded period.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from crosscut_fuzzy.model import AND, FuzzySystem, Rule, Term, Variable

UNIVERSE_POINTS = 201  # resolution of the output universe used for aggregation and centroid
MIN_AREA = 1e-12  # aggregated area below this means "no rule fired": no crisp output


@dataclass(frozen=True)
class OutputResult:
    """Defuzzified output over all samples: crisp value (NaN when no rule fired) and the shape."""

    universe: np.ndarray  # shape (U,)
    crisp: np.ndarray  # shape (n,)
    aggregated: np.ndarray  # shape (n, U)


@dataclass(frozen=True)
class Inference:
    """Result of evaluating a system on n samples."""

    degrees: dict[str, dict[str, np.ndarray]]  # input id -> term name -> membership, shape (n,)
    firing: dict[str, np.ndarray]  # rule id -> firing strength, shape (n,)
    outputs: dict[str, OutputResult]


def membership(term: Term, x: np.ndarray) -> np.ndarray:
    """Membership degree of ``x`` in ``term`` (0..1). Shoulders are allowed: a == b or c == d."""
    x = np.asarray(x, dtype=float)
    if term.shape == "gauss":
        mean, sigma = term.params
        return np.asarray(np.exp(-0.5 * ((x - mean) / sigma) ** 2))
    foot_left, shoulder_left, shoulder_right, foot_right = _trapezoid_corners(term)
    rising = _ramp(x, foot_left, shoulder_left)
    falling = _fall(x, shoulder_right, foot_right)
    return np.asarray(np.minimum(rising, falling))


def _trapezoid_corners(term: Term) -> tuple[float, float, float, float]:
    """Foot-left, shoulder-left, shoulder-right, foot-right; a triangle's top has no width."""
    if term.shape == "tri":
        foot_left, peak, foot_right = term.params
        return foot_left, peak, peak, foot_right
    foot_left, shoulder_left, shoulder_right, foot_right = term.params
    return foot_left, shoulder_left, shoulder_right, foot_right


def _fall(x: np.ndarray, start: float, end: float) -> np.ndarray:
    """1 up to ``start``, 0 beyond ``end``, linear in between; a shoulder keeps 1 at its edge."""
    if end == start:
        return (x <= end).astype(float)
    return np.asarray(np.clip((end - x) / (end - start), 0.0, 1.0))


def _ramp(x: np.ndarray, start: float, end: float) -> np.ndarray:
    """0 below ``start``, 1 above ``end``, linear in between; a step when start == end."""
    if end == start:
        return (x >= end).astype(float)
    return np.asarray(np.clip((x - start) / (end - start), 0.0, 1.0))


def fuzzify(
    system: FuzzySystem, values: Mapping[str, np.ndarray]
) -> dict[str, dict[str, np.ndarray]]:
    """Membership of every input value in every term of its variable."""
    degrees: dict[str, dict[str, np.ndarray]] = {}
    for variable in system.inputs:
        x = np.atleast_1d(np.asarray(values[variable.id], dtype=float))
        degrees[variable.id] = {term.name: membership(term, x) for term in variable.terms}
    return degrees


def rule_strength(rule: Rule, degrees: Mapping[str, Mapping[str, np.ndarray]]) -> np.ndarray:
    """Firing strength: min (AND) or max (OR) of the condition degrees, times the weight."""
    parts = [degrees[clause.variable][clause.term] for clause in rule.conditions]
    stacked = np.stack(parts)
    combined = np.min(stacked, axis=0) if rule.operator == AND else np.max(stacked, axis=0)
    return np.asarray(combined * rule.weight)


def evaluate(system: FuzzySystem, values: Mapping[str, np.ndarray]) -> Inference:
    """Evaluate the system on samples: ``values`` maps input id to an array (or one number)."""
    degrees = fuzzify(system, values)
    n_samples = len(next(iter(next(iter(degrees.values())).values())))
    firing = {
        rule.id: rule_strength(rule, degrees) if rule.enabled else np.zeros(n_samples)
        for rule in system.rules
    }
    outputs = {
        variable.id: _defuzzify(system, variable, firing, n_samples)
        for variable in system.outputs
    }
    return Inference(degrees, firing, outputs)


def _defuzzify(
    system: FuzzySystem, variable: Variable, firing: Mapping[str, np.ndarray], n_samples: int
) -> OutputResult:
    """Aggregate the clipped consequents of one output (max of min) and take the centroid."""
    universe = np.linspace(variable.low, variable.high, UNIVERSE_POINTS)
    shapes = {term.name: membership(term, universe) for term in variable.terms}
    aggregated = np.zeros((n_samples, UNIVERSE_POINTS))
    for rule in system.rules:
        if rule.consequent.variable == variable.id:
            clipped = np.minimum(firing[rule.id][:, None], shapes[rule.consequent.term][None, :])
            aggregated = np.maximum(aggregated, clipped)
    return OutputResult(universe, _centroid(universe, aggregated), aggregated)


def _centroid(universe: np.ndarray, aggregated: np.ndarray) -> np.ndarray:
    """Centre of gravity per sample; NaN where nothing fired."""
    area = aggregated.sum(axis=1)
    safe = np.where(area > MIN_AREA, area, 1.0)
    return np.where(area > MIN_AREA, (aggregated * universe).sum(axis=1) / safe, np.nan)
