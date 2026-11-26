"""Test the committed-evidence audit without loading any process data.

Synthetic report snippets verify parsing and the dimensionless lag penalties.
"""

import pytest
from diagnose import read_development_scores, relative_penalties


def test_development_scores_are_read_without_using_sealed_metrics():
    """Only the explicitly labelled development paragraph supplies scores."""
    report = "validation RMSE on the last 20 % of development 1.116, 1.128, 1.136, 1.143 for"
    assert read_development_scores(report) == (1.116, 1.128, 1.136, 1.143)


def test_missing_development_paragraph_is_rejected():
    """A sealed table cannot silently substitute for development evidence."""
    with pytest.raises(ValueError, match="Expected development"):
        read_development_scores("M2 sealed RMSE 1.1322")


def test_incomplete_candidate_list_is_rejected():
    """All four recorded candidates are needed for the comparison."""
    with pytest.raises(ValueError, match="four positive"):
        read_development_scores("validation RMSE development 1.0, 2.0 for")


def test_relative_penalty_uses_zero_lag_as_reference():
    """RMSE ratios preserve the interpretation of the frozen lag comparison."""
    assert relative_penalties((1.0, 1.1, 1.2, 1.3)) == pytest.approx((0, 0.1, 0.2, 0.3))


def test_zero_reference_is_rejected():
    """A zero denominator must produce a helpful error."""
    with pytest.raises(ValueError, match="four positive"):
        relative_penalties((0.0, 1.0, 2.0, 3.0))
