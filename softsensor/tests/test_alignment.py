"""Synthetic alignment cases with known physical timing and missing-value metadata.

These tests distinguish sampling time, result availability and inferred relative delay.
"""

import numpy as np
import pytest
from crosscut_softsensor.alignment import AlignmentError, align_target, scan_alignment
from crosscut_softsensor.long_format import TagSeries

SCAN_OPTIONS = {"min_delay_s": -10, "max_delay_s": 10, "step_s": 1,
                "bootstrap_samples": 40}


def _delayed_pair() -> tuple[TagSeries, TagSeries]:
    """Return irregular lab samples and a reference recorded four seconds later."""
    generator = np.random.default_rng(38)
    times = np.arange(300.0)
    values = generator.normal(size=len(times))
    indices = np.arange(20, 280, 4)
    return (TagSeries("lab", times[indices], values[indices]),
            TagSeries("online", times + 4, values))


def test_scan_recovers_a_known_positive_delay() -> None:
    """A reference recorded later has a positive recovered delay."""
    lab, reference = _delayed_pair()
    report = scan_alignment(lab, reference, {}, SCAN_OPTIONS)
    assert report["best_delay_s"] == 4
    assert report["interval_low_s"] <= 4 <= report["interval_high_s"]
    assert report["method"] == "paired-bootstrap-95-percent"


def test_scan_removes_a_configured_missing_code_other_than_minus_9999() -> None:
    """A site-specific missing code cannot dominate the correlation profile."""
    lab, reference = _delayed_pair()
    values = lab.values.copy()
    values[3] = 123456
    corrupted = TagSeries(lab.tag, lab.t_s, values)
    report = scan_alignment(corrupted, reference, {"missing_codes": [123456]}, SCAN_OPTIONS)
    assert report["best_delay_s"] == 4
    assert report["pairs"] == len(values) - 1


@pytest.mark.parametrize("meaning,stamp_s", [("start", 100), ("middle", 110), ("end", 120)])
def test_composite_stamp_semantics_reach_the_same_midpoint(meaning: str, stamp_s: float) -> None:
    """Start, midpoint and end stamps describe one physical composite window."""
    series = TagSeries("lab", np.array([stamp_s]), np.array([1.0]))
    metadata = {"stamp": {"meaning": meaning}, "composite_window_s": 20,
                "report_delay_s": 30, "analyser_delay_s": 5}
    aligned = align_target(series, metadata)
    assert aligned.t_s.tolist() == [105]
    assert aligned.available_s.tolist() == [150]


def test_report_delay_changes_availability_without_changing_sample_time() -> None:
    """Lab reporting latency cannot shift the historical training target."""
    series = TagSeries("lab", np.array([100.0]), np.array([1.0]))
    aligned = align_target(series, {"report_delay_s": 30})
    assert aligned.t_s.tolist() == [100]
    assert aligned.available_s.tolist() == [130]


def test_legacy_latency_is_a_report_delay() -> None:
    """Existing catalogue latency remains an availability delay."""
    series = TagSeries("lab", np.array([100.0]), np.array([1.0]))
    aligned = align_target(series, {"latency_s": 30})
    assert aligned.available_s.tolist() == [130]


def test_scan_uses_composite_means_for_end_stamped_samples() -> None:
    """Known window averages recover the reference's five-second delay."""
    generator = np.random.default_rng(9)
    times = np.arange(500.0)
    values = generator.normal(size=len(times))
    ends = np.arange(30, 470, 10)
    means = np.convolve(values, np.ones(7) / 7, mode="valid")[ends - 6]
    lab = TagSeries("lab", ends.astype(float), means)
    reference = TagSeries("online", times + 5, values)
    metadata = {"stamp": {"meaning": "end"}, "composite_window_s": 6}
    assert scan_alignment(lab, reference, metadata, SCAN_OPTIONS)["best_delay_s"] == 5


def test_constant_data_raises_a_helpful_exception() -> None:
    """A delay cannot be inferred from an unchanging signal."""
    lab, reference = _delayed_pair()
    constant = TagSeries(lab.tag, lab.t_s, np.ones(len(lab.values)))
    with pytest.raises(AlignmentError, match="constant"):
        scan_alignment(constant, reference, {}, SCAN_OPTIONS)


def test_scan_rejects_an_unbounded_candidate_grid() -> None:
    """Interactive scans reject ranges that exceed the candidate budget."""
    lab, reference = _delayed_pair()
    options = {**SCAN_OPTIONS, "step_s": 0.0001}
    with pytest.raises(AlignmentError, match="candidates"):
        scan_alignment(lab, reference, {}, options)


def test_scan_recovers_a_known_negative_delay() -> None:
    """A reference recorded earlier has a negative recovered delay."""
    lab, reference = _delayed_pair()
    earlier_reference = TagSeries(reference.tag, reference.t_s - 8, reference.values)
    report = scan_alignment(lab, earlier_reference, {}, SCAN_OPTIONS)
    assert report["best_delay_s"] == -4
    assert report["interval_low_s"] <= -4 <= report["interval_high_s"]


def test_reference_analyser_metadata_removes_a_known_delay() -> None:
    """Configured analyser latency is removed before the residual delay is scanned."""
    lab, reference = _delayed_pair()
    options = {**SCAN_OPTIONS, "reference_metadata": {"analyser_delay_s": 4}}
    report = scan_alignment(lab, reference, {}, options)
    assert report["best_delay_s"] == 0
    assert report["interval_low_s"] <= 0 <= report["interval_high_s"]


def test_noisy_measurements_have_uncertainty_wider_than_one_grid_step() -> None:
    """Measurement noise makes several delays plausible under paired resampling."""
    generator = np.random.default_rng(48)
    times = np.arange(300.0)
    # Smooth variation gives neighboring delay candidates similar physical predictions.
    values = np.convolve(generator.normal(size=300), np.ones(11) / 11, mode="same")
    indices = np.arange(20, 280, 4)
    noise = generator.normal(0, 0.8, len(indices))
    lab = TagSeries("lab", times[indices], values[indices] + noise)
    reference = TagSeries("online", times + 4, values)
    options = {**SCAN_OPTIONS, "bootstrap_samples": 200}
    report = scan_alignment(lab, reference, {}, options)
    assert report["best_delay_s"] == 4
    assert report["interval_low_s"] <= 4 <= report["interval_high_s"]
    assert report["interval_high_s"] - report["interval_low_s"] > options["step_s"]
