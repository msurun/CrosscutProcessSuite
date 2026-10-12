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
    """Membership degree of ``x`` in ``term`` (0..1). Shoulders are allowed: a == b or c == d.

    This is fuzzy-set membership: each input is mapped to a degree between 0 and 1
    (0 = "not in the set at all", 1 = "fully in the set"). A ``term`` is a fuzzy set,
    either a Gaussian bell ("gauss") or a trapezoid defined by four x-positions.

    Returns a float array with one degree per element of ``x``, same shape.
    """
    x = np.asarray(x, dtype=float)
    if term.shape == "gauss":
        # A Gaussian (normal) bell centred on ``mean`` with standard deviation ``sigma``
        # (both in the same unit as ``x``). The exponent -0.5 * ((x - mean) / sigma)**2
        # is the usual normal density term without the 1/(sigma*sqrt(2*pi)) factor, so
        # the peak equals exactly 1 at x == mean. sigma must be > 0.
        mean, sigma = term.params
        return np.asarray(np.exp(-0.5 * ((x - mean) / sigma) ** 2))
    # Trapezoid: read its four corners left to right (units of ``x``):
    # foot_left, shoulder_left, shoulder_right, foot_right. The degree is 0 on the
    # outside feet, rises linearly from foot_left up to 1 at shoulder_left, stays 1
    # across the top, and falls linearly back to 0 at foot_right.
    foot_left, shoulder_left, shoulder_right, foot_right = _trapezoid_corners(term)
    rising = _ramp(x, foot_left, shoulder_left)
    falling = _fall(x, shoulder_right, foot_right)
    # The trapezoid is the intersection (logical AND) of the rising and falling
    # ramps, so its degree is the smaller of the two at every point. Taking the
    # point-wise minimum yields a plateau of 1 wherever both ramps are 1.
    return np.asarray(np.minimum(rising, falling))


def _trapezoid_corners(term: Term) -> tuple[float, float, float, float]:
    """Return the four x-positions that outline a fuzzy membership function.

    A fuzzy set is drawn as a shape along the x-axis: it rises from zero at the
    foot on one side, stays at full membership across the top, then falls to zero
    at the foot on the other side. A shape with a zero-width top is a triangle,
    and one with a real top is a trapezoid; both are described by the same four
    x-coordinates, in metres, ordered left to right:

        (foot_left, shoulder_left, shoulder_right, foot_right)

    Returns:
        The four corner x-positions in metres.

    Raises:
        ValueError: If the parameter count does not match the shape.
    """
    # A triangle has only three stored params (left foot, peak, right foot),
    # but callers always work with four corners, so the peak is duplicated to
    # become a top of zero width. This keeps every shape a four-corner record.
    if term.shape == "tri":
        foot_left, peak, foot_right = term.params
        return foot_left, peak, peak, foot_right
    # A trapezoid already stores four params, and term.params is unpacked here
    # in left-to-right order, matching the corner order the callers expect.
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
    """Aggregate the clipped consequents of one output (max of min) and take the centroid.

    This is the Mamdani defuzzification step. For every rule whose consequent belongs to
    ``variable``, the rule's output fuzzy set is clipped ("min" of the firing strength and the
    consequent's membership function), all clipped sets are unioned with "max", and the
    centre of gravity (centroid) of that union is returned.

    Arguments:
        system: the rule base holding every rule.
        variable: the output variable being defuzzified.
        firing: rule id -> firing strength per sample, shape (n_samples,), values in [0, 1].
        n_samples: number of samples; the batch dimension of every returned array.

    Returns:
        An ``OutputResult`` holding the sampled universe, the centroid per sample (the crisp
        output) and the aggregated membership per sample over the universe.
    """
    # Sample the output's universe (its domain, in physical units) with a fixed grid so the
    # centroid can be integrated numerically. UNIVERSE_POINTS sets the resolution of that grid.
    universe = np.linspace(variable.low, variable.high, UNIVERSE_POINTS)
    # Pre-compute the membership degree of every term of this variable on that grid, so each
    # consequent shape is evaluated once instead of once per rule.
    shapes = {term.name: membership(term, universe) for term in variable.terms}
    # Accumulator for the union ("max") of all clipped consequents. Shape (n_samples,
    # UNIVERSE_POINTS): one membership curve over the universe per input sample.
    aggregated = np.zeros((n_samples, UNIVERSE_POINTS))
    for rule in system.rules:
        # Only rules that write to this output variable contribute to its aggregation.
        if rule.consequent.variable == variable.id:
            # Clip the consequent's shape at the rule's firing strength:
            # clipped[s, u] = min(firing[rule.id][s], shapes[term][u]).
            # The [:, None] / [None, :] pair broadcasts the two 1-D arrays into a
            # (n_samples, UNIVERSE_POINTS) matrix.
            clipped = np.minimum(firing[rule.id][:, None], shapes[rule.consequent.term][None, :])
            # Union with the curves already aggregated: element-wise maximum.
            aggregated = np.maximum(aggregated, clipped)
    # Centroid of each aggregated curve is the crisp output value (same unit as ``universe``).
    return OutputResult(universe, _centroid(universe, aggregated), aggregated)


def _centroid(universe: np.ndarray, aggregated: np.ndarray) -> np.ndarray:
    """Centre of gravity per sample; NaN where nothing fired."""
    area = aggregated.sum(axis=1)
    safe = np.where(area > MIN_AREA, area, 1.0)
    return np.where(area > MIN_AREA, (aggregated * universe).sum(axis=1) / safe, np.nan)
