"""Tests for the benefit estimator that turns PV statistics into a money estimate.

The tests use a synthetic process whose mean, standard deviation and limit are
known exactly, so every expected number in the assertions can be computed by
hand instead of being copied from a previous run.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.benefit import (
    BenefitAssumptions,
    estimate_benefit,
    render_benefit_markdown,
)

PROCESS_MEAN = 100.0
PROCESS_STD = 2.0
LIMIT = 110.0
SAMPLE_COUNT = 1000
SEED = 1234
MARGIN_SIGMAS = 2.0
HALF_STD_REDUCTION = 0.5
VALUE_PER_UNIT_H = 12.5
MIN_VALID_SAMPLES = 30

BEYOND_LIMIT_NOTE = "mean already beyond the limit"
NEAR_LIMIT_NOTE = "limit is already violated or nearly so at current variability"
NO_VALUE_NOTE = "no economic value given"


def make_pv(
    mean: float = PROCESS_MEAN,
    std: float = PROCESS_STD,
    sample_count: int = SAMPLE_COUNT,
    seed: int = SEED,
) -> np.ndarray:
    """Return a deterministic PV array drawn from a normal distribution."""
    rng = np.random.default_rng(seed)
    return mean + std * rng.normal(size=sample_count)


def upper_assumptions(**overrides: float | str) -> BenefitAssumptions:
    """Return a benefit assumption for an upper limit, optionally overridden."""
    fields = {
        "limit": LIMIT,
        "side": "upper",
        "value_per_unit_h": VALUE_PER_UNIT_H,
        "margin_sigmas": MARGIN_SIGMAS,
        "std_reduction": HALF_STD_REDUCTION,
    }
    fields.update(overrides)
    return BenefitAssumptions(**fields)


# Room freed by the variance cut: margin (2 sigma) * std (2) * reduction (0.5).
FREED_ROOM = 2.0


def test_a_known_process_reports_its_standard_deviation_and_target() -> None:
    estimate = estimate_benefit(make_pv(), upper_assumptions())

    assert estimate.std_now == pytest.approx(PROCESS_STD, abs=0.2)
    assert estimate.std_target == pytest.approx(PROCESS_STD / 2, abs=0.1)


def test_a_process_two_sigmas_below_the_limit_frees_two_units_of_room() -> None:
    estimate = estimate_benefit(make_pv(), upper_assumptions())

    assert estimate.shift == pytest.approx(FREED_ROOM, abs=0.3)


def test_the_estimate_records_the_sample_mean_and_used_count() -> None:
    estimate = estimate_benefit(make_pv(), upper_assumptions())

    assert estimate.mean == pytest.approx(PROCESS_MEAN, abs=0.2)
    assert estimate.n_samples_used == SAMPLE_COUNT


def test_a_lower_limit_process_gives_the_same_shift_as_the_mirror_upper_case() -> None:
    pv = make_pv(mean=-100.0)
    assumptions = BenefitAssumptions(limit=-110.0, side="lower", margin_sigmas=MARGIN_SIGMAS)

    estimate = estimate_benefit(pv, assumptions)

    assert estimate.shift == pytest.approx(FREED_ROOM, abs=0.3)


def test_a_lower_limit_mean_above_the_limit_has_a_negative_current_gap() -> None:
    pv = make_pv(mean=-100.0)
    assumptions = BenefitAssumptions(limit=-90.0, side="lower", margin_sigmas=MARGIN_SIGMAS)

    estimate = estimate_benefit(pv, assumptions)

    assert estimate.current_gap < 0


def test_no_std_reduction_frees_no_room() -> None:
    pv = make_pv()
    assumptions = upper_assumptions(std_reduction=0.0)

    estimate = estimate_benefit(pv, assumptions)

    assert estimate.shift == 0.0


def test_the_shift_is_capped_at_the_room_left_before_the_limit() -> None:
    pv = make_pv(mean=109.0, std=2.0)

    estimate = estimate_benefit(pv, upper_assumptions())

    assert estimate.shift == pytest.approx(estimate.current_gap)


def test_nan_samples_are_ignored_and_reduce_the_used_count() -> None:
    pv = make_pv()
    pv[:100] = np.nan

    estimate = estimate_benefit(pv, upper_assumptions())

    assert estimate.n_samples_used == SAMPLE_COUNT - 100


def test_a_mean_beyond_the_limit_yields_no_shift_and_a_warning() -> None:
    pv = make_pv(mean=112.0)

    estimate = estimate_benefit(pv, upper_assumptions())

    assert estimate.shift == 0.0
    assert BEYOND_LIMIT_NOTE in estimate.notes


def test_a_mean_close_to_the_limit_yields_the_near_limit_warning() -> None:
    pv = make_pv(mean=106.0)

    estimate = estimate_benefit(pv, upper_assumptions())

    assert NEAR_LIMIT_NOTE in estimate.notes


def test_a_healthy_loop_produces_no_warning_notes() -> None:
    estimate = estimate_benefit(make_pv(), upper_assumptions())

    assert estimate.notes == ()


def test_a_zero_unit_value_yields_the_no_value_note() -> None:
    estimate = estimate_benefit(make_pv(), upper_assumptions(value_per_unit_h=0.0))

    assert NO_VALUE_NOTE in estimate.notes
    assert estimate.value_per_h == 0.0


def test_the_value_per_hour_is_the_shift_times_the_unit_value() -> None:
    estimate = estimate_benefit(make_pv(), upper_assumptions())

    assert estimate.value_per_h == pytest.approx(estimate.shift * VALUE_PER_UNIT_H, abs=0.01)


def test_fewer_than_thirty_valid_samples_raise_a_value_error() -> None:
    pv = make_pv(sample_count=MIN_VALID_SAMPLES - 1)

    with pytest.raises(ValueError):
        estimate_benefit(pv, upper_assumptions())


def test_an_unknown_limit_side_raises_a_value_error() -> None:
    with pytest.raises(ValueError):
        estimate_benefit(make_pv(), upper_assumptions(side="sideways"))


def test_a_std_reduction_of_one_raises_a_value_error() -> None:
    with pytest.raises(ValueError):
        estimate_benefit(make_pv(), upper_assumptions(std_reduction=1.0))


def test_a_negative_std_reduction_raises_a_value_error() -> None:
    with pytest.raises(ValueError):
        estimate_benefit(make_pv(), upper_assumptions(std_reduction=-0.1))


def test_a_non_positive_margin_in_sigmas_raises_a_value_error() -> None:
    with pytest.raises(ValueError):
        estimate_benefit(make_pv(), upper_assumptions(margin_sigmas=0.0))


def test_a_negative_unit_value_raises_a_value_error() -> None:
    with pytest.raises(ValueError):
        estimate_benefit(make_pv(), upper_assumptions(value_per_unit_h=-1.0))


def test_estimating_does_not_modify_the_input_array() -> None:
    pv = make_pv()
    original = pv.copy()

    estimate_benefit(pv, upper_assumptions())

    assert np.array_equal(pv, original)


def test_the_markdown_states_that_the_number_is_an_estimate() -> None:
    assumptions = upper_assumptions()
    estimate = estimate_benefit(make_pv(), assumptions)

    markdown = render_benefit_markdown(estimate, assumptions)

    assert "estimate" in markdown


def test_the_markdown_contains_every_note() -> None:
    assumptions = upper_assumptions(value_per_unit_h=0.0)
    estimate = estimate_benefit(make_pv(mean=112.0), assumptions)

    markdown = render_benefit_markdown(estimate, assumptions)

    assert BEYOND_LIMIT_NOTE in markdown
    assert NO_VALUE_NOTE in markdown


def test_the_markdown_reports_the_shift_and_the_hourly_value() -> None:
    assumptions = upper_assumptions()
    estimate = estimate_benefit(make_pv(), assumptions)

    markdown = render_benefit_markdown(estimate, assumptions)

    assert f"{estimate.shift:.2f}" in markdown
    assert f"{estimate.value_per_h:.2f}" in markdown
