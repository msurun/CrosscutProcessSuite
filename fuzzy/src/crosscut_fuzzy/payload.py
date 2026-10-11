"""JSON-ready results of the fuzzy system for the web screens: one what-if sample and a replay.

NaN has no JSON form, so a missing crisp output (no rule fired) is returned as ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from crosscut_fuzzy.inference import Inference, evaluate
from crosscut_fuzzy.model import FuzzyModelError, FuzzySystem

DOMINANT_MIN_STRENGTH = 0.05  # a rule counts as "explaining" the output above this firing strength
MAX_REPLAY_POINTS = 5000


def infer_payload(system: FuzzySystem, values: Mapping[str, float]) -> dict[str, Any]:
    """Evaluate one sample: term degrees, rule firing, the aggregated shape and the crisp output."""
    missing = [variable.id for variable in system.inputs if variable.id not in values]
    if missing:
        raise FuzzyModelError(f"missing input values: {', '.join(missing)}")
    arrays = {key: np.array([value], dtype=float) for key, value in values.items()}
    result = evaluate(system, arrays)
    firing = {rule_id: float(strength[0]) for rule_id, strength in result.firing.items()}
    return {
        "inputs": {variable.id: float(values[variable.id]) for variable in system.inputs},
        "degrees": _degrees(result),
        "firing": firing,
        "dominant": _dominant(firing),
        "outputs": _outputs(result),
    }


def _degrees(result: Inference) -> dict[str, dict[str, float]]:
    """Membership degree of the sample in every term of every input."""
    return {
        variable_id: {term: float(degree[0]) for term, degree in terms.items()}
        for variable_id, terms in result.degrees.items()
    }


def _dominant(firing: Mapping[str, float]) -> list[str]:
    """Rules that fire noticeably, strongest first: the one-line "why" of a decision."""
    strong = [(strength, rule_id) for rule_id, strength in firing.items()]
    strong = [item for item in strong if item[0] > DOMINANT_MIN_STRENGTH]
    return [rule_id for _, rule_id in sorted(strong, reverse=True)]


def _outputs(result: Inference) -> dict[str, dict[str, Any]]:
    """Crisp value, universe and aggregated membership shape of every output."""
    return {
        output_id: {
            "crisp": _json_number(float(output.crisp[0])),
            "universe": output.universe.tolist(),
            "aggregated": output.aggregated[0].tolist(),
        }
        for output_id, output in result.outputs.items()
    }


def _json_number(value: float) -> float | None:
    """The number, or None for NaN."""
    return None if np.isnan(value) else value


def replay_payload(
    system: FuzzySystem,
    t_ns: np.ndarray,
    columns: Mapping[str, np.ndarray],
    max_points: int,
) -> dict[str, Any]:
    """Run the system over recorded data; the result is thinned to at most ``max_points`` samples.

    Raises:
        FuzzyModelError: when an input has no tag or a tag is not in the data.
    """
    keep = _thinned_indices(len(t_ns), min(max_points, MAX_REPLAY_POINTS))
    inputs = {
        variable.id: _column(variable.id, variable.tag, columns)[keep] for variable in system.inputs
    }
    result = evaluate(system, inputs)
    return {
        "t": t_ns[keep].tolist(),
        "inputs": {key: _json_list(values) for key, values in inputs.items()},
        "outputs": {key: _json_list(out.crisp) for key, out in result.outputs.items()},
        "actual": _actual_series(system, columns, keep),
    }


def _thinned_indices(n_samples: int, max_points: int) -> np.ndarray:
    """Evenly spread sample indices, at most ``max_points`` of them."""
    return np.linspace(0, n_samples - 1, min(n_samples, max_points)).astype(int)


def _column(variable_id: str, tag: str | None, columns: Mapping[str, np.ndarray]) -> np.ndarray:
    """The data column feeding a variable."""
    if tag is None:
        raise FuzzyModelError(f"variable {variable_id} has no tag, so it cannot be replayed")
    if tag not in columns:
        raise FuzzyModelError(f"tag not in the dataset: {tag}")
    return columns[tag]


def _actual_series(
    system: FuzzySystem, columns: Mapping[str, np.ndarray], keep: np.ndarray
) -> dict[str, list[float | None]]:
    """What the outputs' tags really did, for outputs that name a tag present in the data."""
    return {
        variable.id: _json_list(columns[variable.tag][keep])
        for variable in system.outputs
        if variable.tag is not None and variable.tag in columns
    }


def _json_list(values: np.ndarray) -> list[float | None]:
    """Values as a JSON-safe list (NaN becomes None)."""
    return [None if np.isnan(value) else float(value) for value in values]
