"""Tests for the soft-sensor deployment gate: skill margin, coverage and sample floors.

Pins the pass/refuse behaviour of evaluate_gate and require_deployable and the exact refusal text.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from crosscut_softsensor.deployment_gate import (
    REFUSAL_TEXT,
    DeploymentRefused,
    ValidationResults,
    evaluate_gate,
    require_deployable,
)

BASELINE = "last_good_instrument_value"
# Binary fractions so float64 computes the skill exactly: 1.0 - 0.75 is exactly 0.25,
# which lets the tests sit the skill exactly on the preregistered margin.
MIN_SKILL = 0.25
MIN_COVERAGE = 0.8
MIN_SAMPLES = 500
EXPECTED_REFUSAL_TEXT = (
    "Deployment refused: no validated advantage over the available lab baseline."
)

GATE: dict[str, Any] = {
    "baseline": BASELINE,
    "min_skill": MIN_SKILL,
    "min_scored_coverage": MIN_COVERAGE,
    "min_samples": MIN_SAMPLES,
}


def make_preset() -> dict[str, Any]:
    """Return the preset shape that require_deployable reads the gate from."""
    return {"deployment_gate": GATE}


def make_results(
    rmse_model: float = 0.74,
    rmse_baseline: float = 1.0,
    scored_coverage: float = 0.9,
    n_samples: int = 600,
    baseline: str = BASELINE,
) -> ValidationResults:
    """Return validation results that pass every gate condition.

    The defaults give skill 1.0 - 0.74, which float64 computes exactly and which is just
    above MIN_SKILL; coverage and sample count sit above their minimums.
    """
    return ValidationResults(
        rmse_model=rmse_model,
        rmse_baseline=rmse_baseline,
        scored_coverage=scored_coverage,
        n_samples=n_samples,
        baseline=baseline,
    )


def test_skill_just_above_the_margin_is_deployable() -> None:
    decision = evaluate_gate(GATE, make_results(rmse_model=0.74))
    assert decision.deploy is True
    assert decision.skill == 1.0 - 0.74
    assert decision.reasons == ()
    assert decision.message == "Deployment gate passed."


@pytest.mark.parametrize(
    ("rmse_model", "reason"),
    [
        # skill exactly 0.25: at the margin, and the gate requires strictly above
        (0.75, "skill 0.250 is not above the preregistered margin 0.25"),
        # skill about 0.24: just below the margin
        (0.76, "skill 0.240 is not above the preregistered margin 0.25"),
    ],
)
def test_skill_at_or_below_the_margin_is_refused(rmse_model: float, reason: str) -> None:
    decision = evaluate_gate(GATE, make_results(rmse_model=rmse_model))
    assert decision.deploy is False
    assert decision.reasons == (reason,)
    assert decision.message == REFUSAL_TEXT


def test_coverage_exactly_at_the_minimum_is_deployable() -> None:
    decision = evaluate_gate(GATE, make_results(scored_coverage=0.8))
    assert decision.deploy is True
    assert decision.reasons == ()


def test_coverage_below_the_minimum_is_refused() -> None:
    decision = evaluate_gate(GATE, make_results(scored_coverage=0.79))
    assert decision.deploy is False
    assert decision.reasons == ("scored coverage 0.79 below 0.8",)
    assert decision.message == REFUSAL_TEXT


def test_sample_count_at_the_minimum_is_deployable() -> None:
    decision = evaluate_gate(GATE, make_results(n_samples=500))
    assert decision.deploy is True
    assert decision.reasons == ()


def test_sample_count_one_below_the_minimum_is_refused() -> None:
    decision = evaluate_gate(GATE, make_results(n_samples=499))
    assert decision.deploy is False
    assert decision.reasons == ("sample size 499 below 500",)
    assert decision.message == REFUSAL_TEXT


@pytest.mark.parametrize("rmse_baseline", [0.0, -1.0])
def test_a_baseline_rmse_that_is_not_positive_is_refused(rmse_baseline: float) -> None:
    decision = evaluate_gate(GATE, make_results(rmse_baseline=rmse_baseline))
    assert decision.deploy is False
    assert decision.skill is None
    assert decision.reasons == ("baseline RMSE is not positive; skill undefined",)
    assert decision.message == REFUSAL_TEXT


def test_nan_rmse_metrics_pass_the_gate() -> None:
    # In plain words: the module has no isnan guard, and every gate check is a < or <=
    # comparison, which is False for NaN; all checks are skipped, so the sensor deploys
    # with skill NaN. This documents the behaviour the module really has today.
    decision = evaluate_gate(GATE, make_results(rmse_model=math.nan, rmse_baseline=math.nan))
    assert decision.deploy is True
    assert math.isnan(decision.skill)


def test_the_refusal_text_is_the_preregistered_string() -> None:
    assert REFUSAL_TEXT == EXPECTED_REFUSAL_TEXT


def test_require_deployable_returns_the_passing_decision() -> None:
    decision = require_deployable(make_preset(), make_results())
    assert decision.deploy is True
    assert decision.message == "Deployment gate passed."


@pytest.mark.parametrize(
    "overrides",
    [
        {"rmse_model": 0.75},  # skill exactly at the margin
        {"rmse_model": 0.76},  # skill just below the margin
        {"scored_coverage": 0.79},  # coverage below the minimum
        {"n_samples": 499},  # one sample short of the minimum
        {"rmse_baseline": 0.0},  # skill undefined
    ],
)
def test_require_deployable_raises_the_refusal(overrides: dict[str, float | int]) -> None:
    with pytest.raises(DeploymentRefused) as excinfo:
        require_deployable(make_preset(), make_results(**overrides))
    assert str(excinfo.value) == REFUSAL_TEXT
