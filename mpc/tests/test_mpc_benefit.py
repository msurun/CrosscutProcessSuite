"""Benefit report on the Wood-Berry bed: positive value, no constraint violations."""

from dataclasses import replace

import numpy as np
import pytest
from crosscut_mpc import Economics, FopdtModel, neutral
from crosscut_mpc.benefit import BenefitScenario, simulate_benefit
from mpc_helpers import make_controller


@pytest.fixture(scope="module")
def report() -> dict:
    """Value on top composition, a small steam cost and a CV soft limit as back-off."""
    template = make_controller([[12.8, -18.9], [6.6, -19.4]], cv_lower=[-4.0, -4.0],
                               cv_upper=[4.0, 4.0], mv_lower=np.full(2, -1.0),
                               mv_upper=np.full(2, 1.0), move_max=np.full(2, 0.1),
                               rate_max=np.full(2, 0.1 / 60.0))
    model = FopdtModel(np.array([[12.8, -18.9], [6.6, -19.4]]),
                       np.array([[16.7, 21.0], [10.9, 14.4]]) * 60,
                       np.array([[1.0, 3.0], [7.0, 3.0]]) * 60, 60.0)
    economics = replace(neutral(2, 2), cv_value=np.array([1.0, 0.0]),
                        mv_cost=np.array([0.0, 0.5]), cv_soft_upper=np.array([3.0, 3.0]))
    return simulate_benefit(replace(template, model=model, economics=economics),
                            BenefitScenario(steps=200))


def test_wood_berry_benefit_is_positive(report: dict) -> None:
    assert report["benefit_rate"] > 0
    assert report["value_gained"] > 0
    assert report["economic"]["settled_rate"] > report["tracking"]["settled_rate"]


def test_wood_berry_economic_run_is_constraint_free(report: dict) -> None:
    for branch in ("tracking", "economic"):
        assert all(sum(counts) == 0 for counts in report[branch]["violations"].values())


def test_binding_limits_are_reported_over_time(report: dict) -> None:
    labels = {item for step in report["economic"]["binding_over_time"] for item in step}
    assert labels
    assert report["economic"]["binding"][0]["share"] > 0
    assert len(report["economic"]["binding_over_time"]) == 200


def test_benefit_needs_active_economics() -> None:
    controller = replace(make_controller([[1.0]]), economics=neutral(1, 1))
    with pytest.raises(ValueError, match="active economics"):
        simulate_benefit(controller)
    with pytest.raises(ValueError, match="steps"):
        BenefitScenario(steps=2)


def test_economics_are_part_of_the_public_api() -> None:
    assert isinstance(neutral(1, 1), Economics)
