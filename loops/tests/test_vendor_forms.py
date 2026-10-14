"""Tests for the Siemens and ABB parameter forms (assumption A7)."""

import pytest
from crosscut_loops.tuning_rules import PiSettings
from crosscut_loops.vendor_forms import (
    VENDOR_FORMS,
    abb_pidcc,
    normalise_gain,
    siemens_pid_compact,
    vendor_summaries,
)

PI = PiSettings(kc=2.0, ti_s=120.0)


def test_normalised_gain_scales_by_pv_range_over_output_range():
    assert normalise_gain(2.0, pv_span=1000.0, out_span=100.0) == pytest.approx(20.0)


def test_normalised_gain_is_unchanged_when_both_spans_are_equal():
    assert normalise_gain(2.0, pv_span=100.0, out_span=100.0) == pytest.approx(2.0)


@pytest.mark.parametrize(("pv_span", "out_span"), [(0.0, 100.0), (100.0, 0.0), (-1.0, 100.0)])
def test_normalised_gain_rejects_non_positive_spans(pv_span, out_span):
    with pytest.raises(ValueError):
        normalise_gain(1.0, pv_span, out_span)


def test_siemens_takes_the_raw_gain_and_keeps_ti_in_seconds():
    tags = siemens_pid_compact(PI)
    assert tags["Retain.CtrlParams.Gain"] == pytest.approx(2.0)
    assert tags["Retain.CtrlParams.Ti"] == pytest.approx(120.0)
    assert tags["Retain.CtrlParams.PWeighting"] == 1.0
    assert tags["Retain.CtrlParams.Td"] == 0.0


def test_siemens_gain_is_never_negative_reverse_action_is_a_flag():
    tags = siemens_pid_compact(PI, reverse_acting=True)
    assert tags["Retain.CtrlParams.Gain"] > 0.0
    assert tags["Config.InvertControl"] is True


def test_abb_gain_is_normalised_with_the_ranges():
    assert abb_pidcc(PI, pv_span=50.0, out_span=100.0)["Gain"] == pytest.approx(1.0)


def test_summaries_without_pv_span_leave_abb_tags_empty_and_say_why():
    summary = vendor_summaries(PI, pv_span=None)
    assert summary["siemens_pid_compact"]["tags"]
    assert summary["abb_pidcc"]["tags"] == {}
    assert "PV range not given" in summary["abb_pidcc"]["caveats"][0]


def test_summaries_with_pv_span_fill_both_vendors():
    summary = vendor_summaries(PI, pv_span=100.0)
    assert summary["abb_pidcc"]["tags"]["Gain"] == pytest.approx(2.0)


def test_evidence_levels_are_stated_honestly():
    assert VENDOR_FORMS["siemens_pid_compact"].evidence == "verified"
    assert VENDOR_FORMS["abb_pidcc"].evidence == "partly_verified"


def test_every_form_has_a_source_and_caveats():
    for spec in VENDOR_FORMS.values():
        assert spec.source and spec.caveats


def test_a_non_positive_range_degrades_to_empty_abb_tags_instead_of_raising() -> None:
    summary = vendor_summaries(PI, pv_span=0.0)
    assert summary["abb_pidcc"]["tags"] == {}
    assert summary["siemens_pid_compact"]["tags"]
