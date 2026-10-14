"""Behaviour tests for the PID tuning rules in ``crosscut_loops.tuning_pid``.

The module under test turns a first-order-plus-dead-time (FOPDT) process model
into PID settings (AMIGO, improved SIMC), advises on derivative action, and
converts settings between the ideal and series forms.
"""

from __future__ import annotations

import pytest
from crosscut_loops.tuning_pid import (
    PidSettings,
    amigo_pid,
    derivative_advice,
    high_frequency_gain,
    ideal_to_series,
    normalized_dead_time,
    series_to_ideal,
    simc_pi_improved,
)
from crosscut_loops.tuning_rules import FopdtModel

# A process with gain 2.0, time constant 50 s and 10 s of dead time.
AMIGO_EXAMPLE_MODEL = FopdtModel(gain=2.0, time_constant_s=50.0, delay_s=10.0)


def test_amigo_pid_matches_the_hand_computed_worked_example() -> None:
    settings = amigo_pid(AMIGO_EXAMPLE_MODEL)

    assert settings.kc == pytest.approx(1.225)
    assert settings.ti_s == pytest.approx(29.333333333333332)
    assert settings.td_s == pytest.approx(4.716981132075472)


def test_amigo_pid_gives_positive_settings_bounded_by_the_integral_time() -> None:
    for model in (
        FopdtModel(gain=1.0, time_constant_s=100.0, delay_s=2.0),
        FopdtModel(gain=1.0, time_constant_s=5.0, delay_s=50.0),
    ):
        settings = amigo_pid(model)
        assert settings.kc > 0.0
        assert settings.ti_s > 0.0
        assert settings.td_s < settings.ti_s


def test_amigo_pid_uses_the_default_filter_ratio_of_ten() -> None:
    settings = amigo_pid(AMIGO_EXAMPLE_MODEL)

    assert settings.filter_ratio_n == pytest.approx(10.0)
    assert settings.filter_time_s == pytest.approx(settings.td_s / 10.0)


def test_settings_with_a_non_positive_gain_are_rejected() -> None:
    with pytest.raises(ValueError):
        PidSettings(kc=0.0, ti_s=10.0, td_s=1.0)


def test_settings_with_a_non_positive_integral_time_are_rejected() -> None:
    with pytest.raises(ValueError):
        PidSettings(kc=1.0, ti_s=0.0, td_s=1.0)


def test_settings_with_a_negative_derivative_time_are_rejected() -> None:
    with pytest.raises(ValueError):
        PidSettings(kc=1.0, ti_s=10.0, td_s=-1.0)


def test_settings_with_a_non_positive_filter_ratio_are_rejected() -> None:
    with pytest.raises(ValueError):
        PidSettings(kc=1.0, ti_s=10.0, td_s=1.0, filter_ratio_n=0.0)


def test_improved_simc_pi_matches_the_worked_example() -> None:
    settings = simc_pi_improved(AMIGO_EXAMPLE_MODEL, tau_c_s=10.0)

    assert settings.kc == pytest.approx(1.3333333333333333)
    assert settings.ti_s == pytest.approx(53.333333333333336)


def test_improved_simc_pi_caps_the_integral_time_at_four_tau_c_plus_l() -> None:
    model = FopdtModel(gain=2.0, time_constant_s=500.0, delay_s=10.0)

    settings = simc_pi_improved(model, tau_c_s=10.0)

    assert settings.ti_s == pytest.approx(4.0 * (10.0 + 10.0))


def test_a_non_positive_tau_c_is_rejected() -> None:
    with pytest.raises(ValueError):
        simc_pi_improved(AMIGO_EXAMPLE_MODEL, tau_c_s=0.0)


def test_normalized_dead_time_is_the_delay_over_delay_plus_time_constant() -> None:
    model = FopdtModel(gain=1.0, time_constant_s=90.0, delay_s=10.0)

    assert normalized_dead_time(model) == pytest.approx(0.1)


def test_derivative_is_advised_for_a_lag_dominated_process() -> None:
    model = FopdtModel(gain=1.0, time_constant_s=50.0, delay_s=10.0)

    use_derivative, _ = derivative_advice(model)

    assert use_derivative is True


def test_derivative_is_not_advised_for_a_delay_dominated_process() -> None:
    model = FopdtModel(gain=1.0, time_constant_s=5.0, delay_s=20.0)

    use_derivative, _ = derivative_advice(model)

    assert use_derivative is False


def test_derivative_is_advised_at_the_boundary_normalized_dead_time() -> None:
    model = FopdtModel(gain=1.0, time_constant_s=10.0, delay_s=10.0)

    use_derivative, _ = derivative_advice(model)

    assert use_derivative is True


def test_series_to_ideal_matches_the_hand_computed_conversion() -> None:
    settings = series_to_ideal(kc=1.0, ti_s=20.0, td_s=5.0)

    assert settings.kc == pytest.approx(1.25)
    assert settings.ti_s == pytest.approx(25.0)
    assert settings.td_s == pytest.approx(4.0)


def test_ideal_to_series_round_trips_the_series_to_ideal_conversion() -> None:
    series = series_to_ideal(kc=1.0, ti_s=20.0, td_s=5.0)

    kc, ti_s, td_s = ideal_to_series(series)

    assert (kc, ti_s, td_s) == pytest.approx((1.0, 20.0, 5.0))


def test_ideal_to_series_rejects_an_integral_time_below_four_derivative_times() -> None:
    settings = PidSettings(kc=1.0, ti_s=19.0, td_s=5.0)

    with pytest.raises(ValueError):
        ideal_to_series(settings)


def test_ideal_to_series_is_the_identity_when_the_derivative_time_is_zero() -> None:
    settings = PidSettings(kc=1.0, ti_s=20.0, td_s=0.0)

    kc, ti_s, td_s = ideal_to_series(settings)

    assert (kc, ti_s, td_s) == pytest.approx((1.0, 20.0, 0.0))


def test_high_frequency_gain_scales_the_gain_by_one_plus_the_filter_ratio() -> None:
    settings = PidSettings(kc=2.0, ti_s=10.0, td_s=1.0, filter_ratio_n=8.0)

    assert high_frequency_gain(settings) == pytest.approx(18.0)
