"""Exercise event detection on seeded synthetic daily historian records.

Fault sizes use a nominal 100-unit instrument span and 60-second samples.
"""

from typing import Literal

import numpy as np
import pytest
from crosscut_loops.sensor_faults import (
    SensorFaultConfig,
    SensorFaultFinding,
    detect_sensor_faults,
    estimate_resolution,
    merge_findings,
    score_findings,
)


def daily_signal() -> tuple[np.ndarray, np.ndarray]:
    """Return a quantised AR(1) signal with low normal variability."""
    times = np.arange(0.0, 86400.0, 60.0)
    generator = np.random.default_rng(53)
    noise = generator.normal(0, 0.015, len(times))
    values = np.zeros(len(times))
    for index in range(1, len(times)):
        values[index] = 0.7 * values[index - 1] + noise[index]
    return times, np.round((50 + values) / 0.001) * 0.001


def truth(
    kind: Literal["freeze", "drift", "spike"], start: float, end: float,
) -> SensorFaultFinding:
    """Describe one known injection in seconds."""
    return SensorFaultFinding('level', kind, start, end, 1.0, {})


def test_a_long_freeze_is_found_as_one_event() -> None:
    times, values = daily_signal()
    values[300:391] = 50.0
    findings = detect_sensor_faults(times, values, 'level')
    assert score_findings(findings, [truth('freeze', 18000, 23400)], 60) == (1.0, 1.0)
    assert findings[0].to_dict()['evidence']['duration_s'] >= 5400


def test_a_slow_four_hour_drift_is_found() -> None:
    times, values = daily_signal()
    values += np.clip((times - 28800) / 14400, 0, 1) * 2
    findings = detect_sensor_faults(times, values, 'level')
    precision, recall = score_findings(findings, [truth('drift', 28800, 43200)], 1800)
    assert precision >= 0.9
    assert recall >= 0.8


def test_sparse_returning_spikes_are_found() -> None:
    times, values = daily_signal()
    generator = np.random.default_rng(53)
    injections = (times >= 28800) & (times < 36000) & (generator.random(len(times)) < 0.02)
    values[injections] += 5.0
    findings = detect_sensor_faults(times, values, 'level')
    assert np.count_nonzero(injections) >= 3
    assert score_findings(findings, [truth('spike', 28800, 36000)], 1800) == (1.0, 1.0)


@pytest.mark.parametrize('values', [np.full(1440, 100.0), np.full(1440, 51.23),
                                   np.repeat(np.arange(24), 60)])
def test_naturally_constant_and_staircase_tags_are_not_flagged(values: np.ndarray) -> None:
    times = np.arange(1440) * 60.0
    assert detect_sensor_faults(times, values) == []


def test_a_clean_moving_tag_is_not_flagged() -> None:
    times, values = daily_signal()
    assert detect_sensor_faults(times, values) == []


def test_bad_quality_breaks_a_freeze() -> None:
    times, values = daily_signal()
    values[300:391] = 50.0
    good = np.ones(len(times), dtype=bool)
    good[310:381] = False
    assert detect_sensor_faults(times, values, good=good) == []


def test_a_reference_explains_a_shared_process_ramp() -> None:
    times, values = daily_signal()
    reference = np.clip((times - 28800) / 14400, 0, 1) * 2
    findings = detect_sensor_faults(times, values + reference, reference=reference)
    assert findings == []


def test_duplicate_predictions_only_match_a_truth_once() -> None:
    event = truth('freeze', 100, 200)
    assert score_findings([event, event], [event], 0) == (0.5, 1.0)


def test_matching_respects_tag_kind_and_tolerance() -> None:
    event = truth('freeze', 100, 200)
    assert score_findings([event], [truth('freeze', 210, 300)], 10) == (1.0, 1.0)
    assert score_findings([event], [truth('spike', 100, 200)], 10) == (0.0, 0.0)


def test_empty_event_sets_have_perfect_scores() -> None:
    assert score_findings([], [], 0) == (1.0, 1.0)


@pytest.mark.parametrize('times', [np.array([0, 0, 60]), np.array([0, np.nan, 60])])
def test_invalid_timestamps_raise_a_helpful_error(times: np.ndarray) -> None:
    with pytest.raises(ValueError, match='increasing'):
        detect_sensor_faults(times, np.ones(3))


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match='positive'):
        SensorFaultConfig(window_s=0)


def test_a_valve_pinned_at_its_observed_limit_is_not_a_freeze() -> None:
    times, values = daily_signal()
    values[300:391] = 100.0
    findings = detect_sensor_faults(times, values)
    assert not any(event.kind == 'freeze' for event in findings)


def test_a_coarsely_quantised_level_with_a_long_plateau_is_not_flagged() -> None:
    times, values = daily_signal()
    values = np.round(values / 0.1) * 0.1
    assert detect_sensor_faults(times, values) == []


def test_a_missing_time_gap_does_not_extend_a_short_flat_run() -> None:
    times, values = daily_signal()
    values[300:311] = 50.0
    times[305:] += 5400
    findings = detect_sensor_faults(times, values)
    assert not any(event.kind == 'freeze' for event in findings)


def test_too_few_spikes_do_not_make_a_spiky_window() -> None:
    times, values = daily_signal()
    values[[500]] += 5
    assert detect_sensor_faults(times, values) == []


def test_two_sample_excursions_count_once_each() -> None:
    times, values = daily_signal()
    values[500:502] += 5
    values[510:512] += 5
    values[520:522] += 5
    findings = detect_sensor_faults(times, values, 'level')
    assert score_findings(findings, [truth('spike', 30000, 31320)], 1800) == (1.0, 1.0)


def test_faults_in_one_record_meet_the_event_targets() -> None:
    times, values = daily_signal()
    values[150:241] = 50.0
    values += np.clip((times - 28800) / 14400, 0, 1) * 2
    values[[900, 910, 920, 930]] += 5
    expected = [truth('freeze', 9000, 14400), truth('drift', 28800, 43200),
                truth('spike', 54000, 61200)]
    precision, recall = score_findings(detect_sensor_faults(times, values, 'level'), expected, 1800)
    assert precision >= 0.9
    assert recall >= 0.8


def test_event_matching_finds_the_maximum_assignment() -> None:
    broad = truth('freeze', 100, 400)
    narrow = truth('freeze', 100, 200)
    expected = [truth('freeze', 100, 200), truth('freeze', 300, 400)]
    assert score_findings([broad, narrow], expected, 0) == (1.0, 1.0)


def test_all_missing_values_return_no_events() -> None:
    times, values = daily_signal()
    values[:] = np.nan
    assert detect_sensor_faults(times, values) == []


def test_two_spikes_across_a_window_boundary_form_one_cluster() -> None:
    times, values = daily_signal()
    values[[479, 509]] += 5
    findings = detect_sensor_faults(times, values, "level")
    assert len(findings) == 1
    assert findings[0].evidence["count"] == 2


def test_a_gap_longer_than_the_limit_splits_spike_clusters() -> None:
    times, values = daily_signal()
    indices = np.array([400, 410, 500, 510])
    values[indices + 1] = values[indices - 1]
    values[indices] += 5
    findings = detect_sensor_faults(times, values, "level")
    assert len(findings) == 2


def test_matching_does_not_reuse_a_prediction_for_two_truths() -> None:
    event = truth("freeze", 100, 400)
    expected = [truth("freeze", 100, 200), truth("freeze", 300, 400)]
    assert score_findings([event], expected) == (1.0, 0.5)


def test_matching_calls_do_not_share_visited_state() -> None:
    event = truth("freeze", 100, 200)
    score_findings([event], [event])
    assert score_findings([event], [event]) == (1.0, 1.0)


def test_resolution_requires_twenty_repeated_steps() -> None:
    values = np.arange(10) * 0.001
    assert estimate_resolution(values) < 0.001


def test_resolution_rejects_a_step_above_one_percent_of_range() -> None:
    values = np.tile(np.arange(10), 30).astype(float)
    assert estimate_resolution(values) < 1.0


def test_resolution_accepts_a_supported_fine_lattice() -> None:
    values = np.arange(300) * 0.001
    assert estimate_resolution(values) == pytest.approx(0.001)


def test_nearly_constant_slopes_do_not_produce_a_drift() -> None:
    times = np.arange(1440) * 60.0
    values = times * 1e-8 + np.clip(times - 30000, 0, 12000) * 1e-13
    findings = detect_sensor_faults(times, values, "level")
    assert score_findings(findings, [truth("drift", 0, float(times[-1]))])[1] == 0.0


def test_consecutive_drift_windows_merge_into_one_event() -> None:
    first = SensorFaultFinding("level", "drift", 0, 3600, 5, {
        "slope_per_s": 0.01, "last_window_start_s": 0, "step_s": 1800})
    second = SensorFaultFinding("level", "drift", 1800, 5400, 6, {
        "slope_per_s": 0.02, "last_window_start_s": 1800, "step_s": 1800})
    merged = merge_findings([first, second])
    assert len(merged) == 1
    assert merged[0].end_s == 5400
