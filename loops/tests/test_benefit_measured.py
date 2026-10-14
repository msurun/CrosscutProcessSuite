"""Behaviour of measured variability cuts in the benefit payload.

Covers ``measured_reduction`` and the assumption block of ``benefit_payload``: a request
carrying the PV spread before and after a retune must report that measured cut (source
"retune_measured") instead of the assumed slider value.
"""

from __future__ import annotations

from dataclasses import replace

import crosscut_loops.benefit_payload as benefit_payload_module
import numpy as np
import pytest
from crosscut_loops.benefit_payload import (
    MAX_MEASURED_REDUCTION,
    SOURCE_ASSUMED,
    SOURCE_RETUNE,
    BenefitRequest,
    benefit_payload,
    measured_reduction,
)
from crosscut_loops.overview import LoopTags


def _make_loop() -> LoopTags:
    """The loop under test: PV in degC, no engineering range needed by the payload."""
    return LoopTags(
        name="L", pv="PV", sp="SP", out="OUT", mode="MODE", unit="degC", eng_min=None, eng_max=None
    )


def _make_columns() -> dict[str, np.ndarray]:
    """PV history: 3000 samples around 50 degC with a spread of 1 degC (seeded, repeatable)."""
    return {"PV": 50.0 + np.random.default_rng(0).normal(0.0, 1.0, 3000)}


def _make_time() -> np.ndarray:
    """Timestamps of the samples: one per second, starting at zero."""
    return np.arange(3000, dtype=float)


def test_measured_reduction_halves_between_two_and_one():
    request = BenefitRequest(std_before=2.0, std_after=1.0)
    assert measured_reduction(request) == pytest.approx(0.5)


def test_measured_reduction_is_none_without_a_before_spread():
    request = BenefitRequest(std_before=None, std_after=1.0)
    assert measured_reduction(request) is None


def test_measured_reduction_is_none_without_an_after_spread():
    request = BenefitRequest(std_before=2.0, std_after=None)
    assert measured_reduction(request) is None


def test_measured_reduction_is_none_when_the_before_spread_is_zero():
    request = BenefitRequest(std_before=0.0, std_after=1.0)
    assert measured_reduction(request) is None


def test_a_retune_that_worsened_the_spread_counts_as_no_reduction():
    request = BenefitRequest(std_before=1.0, std_after=2.0)
    assert measured_reduction(request) == 0.0


def test_a_fully_removed_spread_is_capped_before_it_reaches_one():
    request = BenefitRequest(std_before=2.0, std_after=0.0)
    assert measured_reduction(request) == MAX_MEASURED_REDUCTION


def test_a_payload_without_a_measurement_reports_the_assumed_reduction():
    request = BenefitRequest(value_per_unit_h=1.0, std_reduction=0.5)
    payload = benefit_payload(_make_loop(), _make_time(), _make_columns(), request)
    assumptions = payload["assumptions"]
    assert assumptions["std_reduction_source"] == SOURCE_ASSUMED
    assert assumptions["std_reduction"] == pytest.approx(0.5)
    assert assumptions["std_before"] is None


def test_a_payload_with_a_measurement_reports_the_retune_numbers():
    request = BenefitRequest(
        value_per_unit_h=1.0, std_reduction=0.1, std_before=2.0, std_after=1.0
    )
    payload = benefit_payload(_make_loop(), _make_time(), _make_columns(), request)
    assumptions = payload["assumptions"]
    assert assumptions["std_reduction_source"] == SOURCE_RETUNE
    assert assumptions["std_reduction"] == pytest.approx(0.5)
    assert assumptions["std_before"] == pytest.approx(2.0)
    assert assumptions["std_after"] == pytest.approx(1.0)


def test_the_measured_cut_narrows_the_target_spread_by_half():
    request = BenefitRequest(
        value_per_unit_h=1.0, std_reduction=0.1, std_before=2.0, std_after=1.0
    )
    payload = benefit_payload(_make_loop(), _make_time(), _make_columns(), request)
    estimate = payload["estimate"]
    assert estimate["std_target"] == pytest.approx(estimate["std_now"] * 0.5, abs=1e-9)


def test_a_nan_spread_before_the_retune_gives_no_measured_reduction():
    """A NaN or infinite spread is not a measurement, so the assumed cut stays in force."""
    nan, inf = float("nan"), float("inf")
    assert measured_reduction(BenefitRequest(std_before=nan, std_after=1.0)) is None
    assert measured_reduction(BenefitRequest(std_before=2.0, std_after=nan)) is None
    assert measured_reduction(BenefitRequest(std_before=inf, std_after=1.0)) is None


def test_a_note_without_a_name_is_reported_with_its_own_text(monkeypatch):
    """An unknown note from the estimator passes through as text instead of raising KeyError."""
    real_estimate = benefit_payload_module.estimate_benefit

    def estimate_with_new_note(pv, assumptions):
        return replace(real_estimate(pv, assumptions), notes=("a brand new warning",))

    monkeypatch.setattr(benefit_payload_module, "estimate_benefit", estimate_with_new_note)

    payload = benefit_payload(_make_loop(), _make_time(), _make_columns(), BenefitRequest())

    assert payload["notes"] == ["a brand new warning"]
