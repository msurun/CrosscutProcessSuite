"""Tests for the "not assessed instead of guessed" feature of loop analysis.

The analysis must never draw conclusions from per-loop knowledge it does not have
(engineering output range, process dead time, oscillation limits). These tests pin
down which conclusions are withheld and how the gaps are reported.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_loops.monitor import (
    DELAY,
    KNOWN_ALL,
    OSCILLATION_LIMITS,
    OUT_RANGE,
    LoopReport,
    LoopSettings,
    analyze_loop,
)
from crosscut_loops.overview import LoopTags, default_settings, health_percent
from crosscut_sim.core import AUTO

DT = 10.0
SAMPLE_COUNT = 2160
NOISE_SEED = 1234  # each signal builder starts its own generator: no dependence on test order

SATURATION_FRACTION = 0.5
SINE_PERIOD_S = 600.0
SINE_NOISE = 0.05
AR1_COEFFICIENT = 0.97
HARRIS_POOR_THRESHOLD = 0.3


def base_settings(**overrides) -> LoopSettings:
    """Base settings with sensible defaults, overridable per test."""
    values = {"delay_s": DT, "ultimate_period_s": SINE_PERIOD_S, "amplitude_limit": 0.2}
    values.update(overrides)
    return LoopSettings(**values)


def signals(errors: np.ndarray, out: float = 50.0) -> tuple:
    """Build (t, pv, sp, out, mode) arrays from a per-sample error sequence."""
    sp_value = 10.0
    t_s = np.arange(len(errors)) * DT
    sp = np.full(len(errors), sp_value)
    out_array = np.full(len(errors), out)
    mode_array = np.full(len(errors), AUTO)
    return t_s, sp + errors, sp, out_array, mode_array


def saturated_errors() -> np.ndarray:
    """Errors for the saturated case: a constant step offset."""
    return np.full(SAMPLE_COUNT, 1.0)


def sluggish_errors() -> np.ndarray:
    """Return an AR(1) error sequence typical of a sluggish loop."""
    noise = np.random.default_rng(NOISE_SEED)
    errors = np.zeros(SAMPLE_COUNT)
    for k in range(1, SAMPLE_COUNT):
        errors[k] = AR1_COEFFICIENT * errors[k - 1] + noise.normal(scale=SINE_NOISE)
    return errors


def sine_errors() -> np.ndarray:
    """Return a periodic error plus noise, typical of an oscillating loop."""
    t_s = np.arange(SAMPLE_COUNT) * DT
    noise = np.random.default_rng(NOISE_SEED)
    sine = np.sin(2 * np.pi * t_s / SINE_PERIOD_S)
    return sine + noise.normal(scale=SINE_NOISE, size=SAMPLE_COUNT)


def analyze_saturated(settings: LoopSettings) -> LoopReport:
    """Analyze the saturated case (output at 100 for the first half)."""
    t_s, pv, sp, _, mode = signals(saturated_errors(), out=50.0)
    out = np.where(t_s < SAMPLE_COUNT * DT / 2, 100.0, 50.0)
    return analyze_loop(t_s, pv, sp, out, mode, settings=settings)


def analyze_sluggish(settings: LoopSettings) -> LoopReport:
    """Analyze the sluggish AR(1) case."""
    t_s, pv, sp, out, mode = signals(sluggish_errors())
    return analyze_loop(t_s, pv, sp, out, mode, settings=settings)


def analyze_sine(settings: LoopSettings) -> LoopReport:
    """Analyze the oscillating sine case."""
    t_s, pv, sp, out, mode = signals(sine_errors())
    return analyze_loop(t_s, pv, sp, out, mode, settings=settings)


def no_range_settings() -> LoopSettings:
    """Base settings with the output range unknown."""
    return base_settings(known=KNOWN_ALL - {OUT_RANGE})


def no_delay_settings() -> LoopSettings:
    """Base settings with the dead time unknown."""
    return base_settings(known=KNOWN_ALL - {DELAY})


def no_oscillation_settings() -> LoopSettings:
    """Base settings with the oscillation limits unknown."""
    return base_settings(known=KNOWN_ALL - {OSCILLATION_LIMITS})


def empty_known_settings() -> LoopSettings:
    """Base settings with no per-loop knowledge at all."""
    return base_settings(known=frozenset())


def test_known_all_classifies_saturated_case():
    """With full knowledge, half the record at output 100 gives a saturation fraction of 0.5."""
    report = analyze_saturated(base_settings())
    assert report.saturation_fraction == pytest.approx(SATURATION_FRACTION)


def test_known_all_classifies_saturated_case_label():
    """With full knowledge, the saturated case is classified "saturated"."""
    report = analyze_saturated(base_settings())
    assert report.classification == "saturated"


def test_known_all_classifies_oscillating_case():
    """With full knowledge, a regular sine error is classified "oscillating"."""
    report = analyze_sine(base_settings())
    assert report.classification == "oscillating"


def test_known_all_classifies_poor_performance_case():
    """With full knowledge, a sluggish AR(1) error is poor performance."""
    report = analyze_sluggish(base_settings())
    assert report.classification == "poor_performance"


def test_known_all_reports_nothing_as_not_assessed():
    """When every piece of knowledge is configured, nothing is listed as not assessed."""
    report = analyze_sine(base_settings())
    assert report.not_assessed == ()


def test_without_out_range_the_loop_is_not_saturated():
    """Without the output range, saturation cannot be judged, so it is not claimed."""
    report = analyze_saturated(no_range_settings())
    assert report.classification != "saturated"


def test_without_out_range_the_saturation_fraction_is_nan():
    """An unknown saturation is NaN rather than a made-up 0 that would look like a healthy valve."""
    report = analyze_saturated(no_range_settings())
    assert np.isnan(report.saturation_fraction)


def test_without_out_range_valve_kpis_are_none():
    """Valve travel, reversals and sizing hint need the output range and are None without it."""
    report = analyze_saturated(no_range_settings())
    assert report.valve_travel_per_h is None
    assert report.valve_reversals_per_h is None
    assert report.valve_sizing_hint is None


def test_without_out_range_saturation_and_valve_kpis_are_not_assessed():
    """The skipped saturation and valve checks are named in not_assessed so the gap is visible."""
    report = analyze_saturated(no_range_settings())
    assert "saturation" in report.not_assessed
    assert "valve_kpis" in report.not_assessed


def test_without_out_range_the_quantisation_ratio_is_still_computed():
    """The quantisation ratio needs no range, so it is still computed."""
    errors = np.full(SAMPLE_COUNT, 0.5)
    t_s, pv, sp, _, mode = signals(errors)
    noise = np.random.default_rng(NOISE_SEED)
    quantised = np.round(50 + noise.normal(scale=0.3, size=SAMPLE_COUNT) / 1.0) * 1.0
    report = analyze_loop(t_s, pv, sp, quantised, mode, settings=no_range_settings())
    assert report.out_quantisation_ratio is not None


def test_without_delay_the_harris_index_is_nan():
    """Without the dead time the Harris index cannot be computed and is NaN."""
    report = analyze_sluggish(no_delay_settings())
    assert np.isnan(report.harris_index)


def test_without_delay_the_loop_is_not_poor_performance():
    """Without a Harris index the loop must not be classified as poor performance."""
    report = analyze_sluggish(no_delay_settings())
    assert report.classification != "poor_performance"


def test_without_delay_harris_is_not_assessed():
    """The skipped Harris check is named in not_assessed."""
    report = analyze_sluggish(no_delay_settings())
    assert "harris" in report.not_assessed


def test_without_oscillation_limits_the_acf_method_finds_the_cycle():
    """Without limits the parameter-free ACF method still finds the 600 s cycle."""
    report = analyze_sine(no_oscillation_settings())
    assert report.oscillation_method == "acf"
    assert report.oscillation_period_s == pytest.approx(SINE_PERIOD_S, rel=0.05)


def test_without_oscillation_limits_a_regular_cycle_is_oscillating():
    """A regular cycle is flagged oscillating even when its amplitude cannot be judged."""
    report = analyze_sine(no_oscillation_settings())
    assert report.classification == "oscillating"
    assert any("amplitude is tolerable is not assessed" in finding for finding in report.findings)


def test_without_oscillation_limits_sluggish_noise_is_not_oscillating():
    """Correlated noise is not mistaken for an oscillation, with only the limits unknown
    and with no per-loop knowledge at all."""
    for settings in (no_oscillation_settings(), empty_known_settings()):
        report = analyze_sluggish(settings)
        assert report.oscillation_period_s is None
        assert report.classification != "oscillating"


def test_without_oscillation_limits_the_amplitude_is_not_assessed():
    """Whether the amplitude is tolerable is listed as not assessed without limits."""
    report = analyze_sine(no_oscillation_settings())
    assert "oscillation_amplitude" in report.not_assessed


def test_with_limits_the_hagglund_method_is_used():
    """With limits configured, the Hagglund method is used instead of ACF."""
    report = analyze_sine(base_settings())
    assert report.oscillation_method == "hagglund"
    assert report.oscillation_regularity is None


def test_with_no_knowledge_not_assessed_lists_gaps_in_fixed_order():
    """The not_assessed list has a fixed order so reports and the UI stay stable."""
    report = analyze_sine(empty_known_settings())
    expected = ("saturation", "valve_kpis", "harris", "oscillation_amplitude")
    assert report.not_assessed == expected


def tags(**given: float) -> LoopTags:
    """A loop L1 with no per-loop knowledge except the fields given."""
    fields: dict[str, float | None] = {"eng_min": None, "eng_max": None}
    fields.update(given)
    return LoopTags("L1", "L1", "L1_sp", "L1_out", "L1_mode", "bar", **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "given, expected",
    [
        ({}, frozenset()),
        ({"out_low": 0.0, "out_high": 100.0}, frozenset({OUT_RANGE})),
        ({"out_low": 0.0}, frozenset()),
        ({"delay_s": 5.0}, frozenset({DELAY})),
        ({"ultimate_period_s": 120.0, "amplitude_limit": 0.4}, frozenset({OSCILLATION_LIMITS})),
        (
            {"ultimate_period_s": 120.0, "eng_min": 0.0, "eng_max": 100.0},
            frozenset({OSCILLATION_LIMITS}),
        ),
        ({"ultimate_period_s": 120.0}, frozenset()),
        ({"amplitude_limit": 0.4}, frozenset()),
    ],
)
def test_default_settings_knows_only_what_the_tags_provide(
    given: dict[str, float], expected: frozenset[str]
) -> None:
    """A kind of knowledge counts as known only if all the tag fields it needs are set."""
    settings = default_settings(tags(**given))
    assert settings.known == expected


def build_ok_report(saturation_fraction: float) -> LoopReport:
    """Build a minimal OK report with the given saturation fraction."""
    return LoopReport(
        n_samples=SAMPLE_COUNT,
        service_factor=1.0,
        saturation_fraction=saturation_fraction,
        flatline_fraction=0.0,
        mode_changes=0,
        mean_abs_error=0.1,
        error_std=0.1,
        harris_index=0.8,
        oscillation_period_s=None,
        classification="ok",
        findings=[],
    )


def test_unknown_saturation_is_not_penalised_in_health_percent():
    """An unknown saturation costs no health points, the same as zero saturation."""
    unknown_saturation = build_ok_report(np.nan)
    zero_saturation = build_ok_report(0.0)
    assert health_percent(unknown_saturation) == health_percent(zero_saturation)
