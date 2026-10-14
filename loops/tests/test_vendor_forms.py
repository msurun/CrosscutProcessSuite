"""Tests for the Siemens and ABB parameter forms (assumption A7)."""

import pytest
from crosscut_loops.tuning_rules import PiSettings
from crosscut_loops.vendor_forms import (
    VENDOR_FORMS,
    abb_pidcc,
    siemens_gain,
    siemens_pid_compact,
)

PI = PiSettings(kc=2.0, ti_s=120.0)


def test_siemens_gain_is_scaled_by_the_range_ratio():
    assert siemens_gain(2.0, pv_span=1000.0, out_span=100.0) == pytest.approx(0.2)


def test_siemens_gain_is_unchanged_when_both_spans_are_equal():
    assert siemens_gain(2.0, pv_span=100.0, out_span=100.0) == pytest.approx(2.0)


@pytest.mark.parametrize(("pv_span", "out_span"), [(0.0, 100.0), (100.0, 0.0), (-1.0, 100.0)])
def test_siemens_gain_rejects_non_positive_spans(pv_span, out_span):
    with pytest.raises(ValueError):
        siemens_gain(1.0, pv_span, out_span)


def test_siemens_tags_keep_ti_in_seconds_and_weight_the_setpoint_fully():
    tags = siemens_pid_compact(PI, pv_span=100.0)
    assert tags["Retain.CtrlParams.Ti"] == pytest.approx(120.0)
    assert tags["Retain.CtrlParams.PWeighting"] == 1.0
    assert tags["Retain.CtrlParams.Td"] == 0.0


def test_siemens_gain_is_never_negative_reverse_action_is_a_flag():
    tags = siemens_pid_compact(PI, pv_span=100.0, reverse_acting=True)
    assert tags["Retain.CtrlParams.Gain"] > 0.0
    assert tags["Config.InvertControl"] is True


def test_abb_gain_needs_no_range_scaling():
    assert abb_pidcc(PI)["Gain"] == pytest.approx(2.0)


def test_evidence_levels_are_stated_honestly():
    assert VENDOR_FORMS["siemens_pid_compact"].evidence == "verified"
    assert VENDOR_FORMS["abb_pidcc"].evidence == "partly_verified"


def test_every_form_has_a_source_and_caveats():
    for spec in VENDOR_FORMS.values():
        assert spec.source and spec.caveats
