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


@pytest.mark.slow
def test_tf3_gain_mismatch_restores_the_entire_set(tmp_path: Path, checkout: None) -> None:
    """A delayed Gain mismatch is reported, holds the target off and is never reverted."""
    reject_mismatched_gain(tmp_path)


@pytest.mark.slow
def test_tf4_small_ti_offset_is_accepted(tmp_path: Path, checkout: None) -> None:
    """An offset inside Ti tolerance must not trigger a false mismatch or revert."""
    accept_tolerated_ti_offset(tmp_path)
