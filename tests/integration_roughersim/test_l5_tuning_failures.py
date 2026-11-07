"""Run L5 TF1..TF4 against the pinned RougherSim release.

Skip when the checkout is unavailable; preserve unsafe restoration as a strict expected failure.
"""

from pathlib import Path

import pytest
from golden import checkout_problem, load_pin, roughersim_dir
from tuning_failure_rows import (
    accept_tolerated_ti_offset,
    reject_gain_change,
    reject_mismatched_gain,
)


@pytest.fixture(scope="module")
def checkout() -> None:
    """Skip the module unless the sibling RougherSim checkout is the pinned release."""
    problem = checkout_problem(roughersim_dir(), load_pin())
    if problem:
        pytest.skip(problem)


@pytest.mark.slow
def test_tf1_type_mismatch_preserves_gain(tmp_path: Path, checkout: None) -> None:
    """BadTypeMismatch stops and audits Gain without changing tuning or loop ownership."""
    reject_gain_change(tmp_path, "tf1_type_mismatch")


@pytest.mark.slow
def test_tf2_not_writable_preserves_gain(tmp_path: Path, checkout: None) -> None:
    """BadNotWritable stops and audits Gain without changing tuning or loop ownership."""
    reject_gain_change(tmp_path, "tf2_not_writable")


# FINDING: Source inspection (not live observation): an active offset enters from_value.
# Partial revert writes that biased baseline back; expiry exposes changed stored Gain.
# Keep the original-plant assertion: alarming/stopping alone does not restore atomicity.
@pytest.mark.slow
@pytest.mark.xfail(
    strict=True,
    reason=(
        "TF3 live finding: with hooks RougherSim shows a written value only after the next step "
        "(offset appears one step late); the gateway reads back once at write time, so a delayed "
        "divergence is not detected. Needs delayed read-back verification (ADR 014 follow-up)."
    ),
    raises=AssertionError,
)
def test_tf3_gain_mismatch_restores_the_entire_set(tmp_path: Path, checkout: None) -> None:
    """A readback mismatch must leave neither Gain nor the earlier Ti change applied."""
    reject_mismatched_gain(tmp_path)


@pytest.mark.slow
def test_tf4_small_ti_offset_is_accepted(tmp_path: Path, checkout: None) -> None:
    """An offset inside Ti tolerance must not trigger a false mismatch or revert."""
    accept_tolerated_ti_offset(tmp_path)
