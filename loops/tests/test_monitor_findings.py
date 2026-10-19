"""Tests for the sentences that monitor._findings builds from a finished LoopReport.

Only the sentence of the loop's own classification may be built: a message for a class the
loop does not have must never be evaluated, because its inputs can legitimately be missing.
"""

from __future__ import annotations

from crosscut_loops.monitor import OSC_ACF, LoopReport, _classification_findings


def _report(classification: str, **overrides: object) -> LoopReport:
    """A LoopReport with neutral numbers; ``overrides`` replace single fields."""
    fields: dict[str, object] = {
        "n_samples": 1000,
        "service_factor": 0.3,
        "saturation_fraction": 0.0,
        "flatline_fraction": 0.0,
        "mode_changes": 0,
        "mean_abs_error": 0.1,
        "error_std": 0.1,
        "harris_index": 0.8,
        "oscillation_period_s": None,
        "classification": classification,
        "findings": [],
    }
    fields.update(overrides)
    return LoopReport(**fields)  # type: ignore[arg-type]


def test_a_manual_loop_gets_only_the_manual_sentence() -> None:
    """The manual sentence is returned and no other class's sentence is built."""
    found = _classification_findings(_report("manual"))
    assert found == ["manual: in use only 30% of the time"]


def test_an_acf_method_without_a_period_does_not_break_other_classes() -> None:
    """A report that names the ACF method but has no period must not raise for a manual loop."""
    report = _report("manual", oscillation_method=OSC_ACF, oscillation_period_s=None)
    assert _classification_findings(report) == ["manual: in use only 30% of the time"]


def test_an_ok_loop_has_no_classification_sentence() -> None:
    """A healthy loop gets no sentence from its classification."""
    assert _classification_findings(_report("ok")) == []


def test_an_oscillating_acf_loop_names_the_period_and_the_caveat() -> None:
    """The ACF sentence carries the period, the regularity and the false-alarm caveat."""
    report = _report(
        "oscillating",
        oscillation_method=OSC_ACF,
        oscillation_period_s=120.0,
        oscillation_regularity=1.4,
    )
    (sentence,) = _classification_findings(report)
    assert "120 s period" in sentence
    assert "ACF regularity 1.4" in sentence
    assert "confirm the cycle on the trend" in sentence
