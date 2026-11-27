"""Deployment gate: a soft sensor leaves shadow only with a validated advantage over the lab.

Rule from the exp39 diagnosis (#154): skill must be measured against the strongest causal
baseline (age-aware persistence of the last released lab value, same information cutoff) and clear
a preregistered margin, with enough scored coverage and samples. No shadow-to-deployed step exists
in the code yet; #157 calls ``evaluate_gate`` / ``require_deployable`` at that step.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

REFUSAL_TEXT = "Deployment refused: no validated advantage over the available lab baseline."


class DeploymentRefused(RuntimeError):
    """Raised when a preset or sensor may not be deployed; the message is the refusal text."""


@dataclass(frozen=True)
class ValidationResults:
    """Validation outcome on rows scored once, on the same rows for model and baseline.

    ``rmse_baseline`` is the strongest causal baseline at the same information cutoff;
    ``scored_coverage`` is scored rows / rows that should be scored (0..1); ``n_samples`` is the
    number of scored lab samples.
    """

    rmse_model: float
    rmse_baseline: float
    scored_coverage: float
    n_samples: int
    baseline: str
    same_information_cutoff: bool = True


@dataclass(frozen=True)
class GateDecision:
    """Pass or refuse; ``reasons`` explain a refusal, ``message`` is the user-facing text."""

    deploy: bool
    skill: float | None
    reasons: tuple[str, ...]
    message: str


def skill_score(rmse_model: float, rmse_baseline: float) -> float | None:
    """Skill 1 - RMSE_model / RMSE_baseline; None when the baseline RMSE is not positive."""
    if rmse_baseline <= 0:
        return None
    return 1.0 - rmse_model / rmse_baseline


def evaluate_gate(gate: Mapping[str, Any], results: ValidationResults) -> GateDecision:
    """Apply a preset's ``deployment_gate`` to validation results.

    Passes only when skill is strictly above ``min_skill``, coverage and sample size reach their
    minimums, and the baseline is the declared one at the same information cutoff.
    """
    skill = skill_score(results.rmse_model, results.rmse_baseline)
    reasons = _reasons(gate, results, skill)
    if reasons:
        return GateDecision(False, skill, tuple(reasons), REFUSAL_TEXT)
    return GateDecision(True, skill, (), "Deployment gate passed.")


def _reasons(
    gate: Mapping[str, Any], results: ValidationResults, skill: float | None
) -> list[str]:
    """Collect every failed condition."""
    reasons: list[str] = []
    if results.baseline != gate["baseline"]:
        reasons.append(f"baseline {results.baseline!r} is not the declared {gate['baseline']!r}")
    if not results.same_information_cutoff:
        reasons.append("model and baseline were not scored at the same information cutoff")
    if skill is None:
        reasons.append("baseline RMSE is not positive; skill undefined")
    elif skill <= gate["min_skill"]:
        margin = gate["min_skill"]
        reasons.append(f"skill {skill:.3f} is not above the preregistered margin {margin}")
    if results.scored_coverage < gate["min_scored_coverage"]:
        floor = gate["min_scored_coverage"]
        reasons.append(f"scored coverage {results.scored_coverage:.2f} below {floor}")
    if results.n_samples < gate["min_samples"]:
        reasons.append(f"sample size {results.n_samples} below {gate['min_samples']}")
    return reasons


def require_deployable(preset: Mapping[str, Any], results: ValidationResults) -> GateDecision:
    """Gate for the shadow-to-deployed step: return the decision or raise DeploymentRefused."""
    decision = evaluate_gate(preset["deployment_gate"], results)
    if not decision.deploy:
        raise DeploymentRefused(decision.message)
    return decision
