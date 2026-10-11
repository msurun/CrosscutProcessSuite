"""Behaviour tests for the tuning-rule formulas in ``crosscut_loops.tuning_rules``.

The module under test turns a first-order-plus-dead-time (FOPDT) process model
into PI controller settings using two well-known rules (SIMC and AMIGO), and
converts those settings into the parameter forms used by different vendors.
"""

from __future__ import annotations

import pytest
from crosscut_loops.tuning_rules import (
    FopdtModel,
    PiSettings,
    amigo_pi,
    convert_pi,
    lambda_from_robustness,
    simc_pi,
)

# A process with gain 2.0, time constant 100 s and 10 s of dead time.
SIMC_EXAMPLE_MODEL = FopdtModel(gain=2.0, time_constant_s=100.0, delay_s=10.0)
# A process with gain 1.0, time constant 10 s and 2 s of dead time.
AMIGO_EXAMPLE_MODEL = FopdtModel(gain=1.0, time_constant_s=10.0, delay_s=2.0)


def test_simc_pi_matches_the_worked_example() -> None:
    settings = simc_pi(SIMC_EXAMPLE_MODEL, tau_c_s=10.0)

    assert settings.kc == pytest.approx(2.5)
    assert settings.ti_s == pytest.approx(80.0)


def test_amigo_pi_matches_the_worked_example() -> None:
    settings = amigo_pi(AMIGO_EXAMPLE_MODEL)

    assert settings.kc == pytest.approx(1.2055555555555553)
    assert settings.ti_s == pytest.approx(7.765217391304348)


def test_simc_pi_yields_a_smaller_gain_for_a_larger_robustness() -> None:
    gains = [
        simc_pi(SIMC_EXAMPLE_MODEL, tau_c_s=lambda_from_robustness(SIMC_EXAMPLE_MODEL, level)).kc
        for level in (0.0, 0.5, 1.0)
    ]

    assert gains[0] > gains[1] > gains[2]


def test_simc_pi_integral_time_never_grows_smaller_when_robustness_increases() -> None:
    integral_times = [
        simc_pi(SIMC_EXAMPLE_MODEL, tau_c_s=lambda_from_robustness(SIMC_EXAMPLE_MODEL, level)).ti_s
        for level in (0.0, 0.5, 1.0)
    ]

    assert integral_times[0] <= integral_times[1] <= integral_times[2]


def test_amigo_pi_yields_a_smaller_gain_for_a_larger_robustness() -> None:
    # AMIGO has no tuning slider; the equivalent effect is shown through SIMC.
    gains = [
        simc_pi(AMIGO_EXAMPLE_MODEL, tau_c_s=lambda_from_robustness(AMIGO_EXAMPLE_MODEL, level)).kc
        for level in (0.0, 0.5, 1.0)
    ]

    assert gains[0] > gains[1] > gains[2]


def test_simc_pi_caps_the_integral_time_at_the_process_time_constant() -> None:
    settings = simc_pi(SIMC_EXAMPLE_MODEL, tau_c_s=1000.0)

    assert settings.ti_s == pytest.approx(SIMC_EXAMPLE_MODEL.time_constant_s)


def test_lambda_from_robustness_is_the_delay_at_the_fastest_end() -> None:
    tau_c_s = lambda_from_robustness(SIMC_EXAMPLE_MODEL, robustness=0.0)

    assert tau_c_s == pytest.approx(10.0)


def test_lambda_from_robustness_is_three_delays_at_the_middle() -> None:
    tau_c_s = lambda_from_robustness(SIMC_EXAMPLE_MODEL, robustness=0.5)

    assert tau_c_s == pytest.approx(30.0)


def test_lambda_from_robustness_is_five_delays_at_the_robust_end() -> None:
    tau_c_s = lambda_from_robustness(SIMC_EXAMPLE_MODEL, robustness=1.0)

    assert tau_c_s == pytest.approx(50.0)


def test_gain_seconds_form_keeps_the_gain_and_the_integral_time_in_seconds() -> None:
    converted = convert_pi(PiSettings(kc=2.0, ti_s=120.0), form="gain_seconds")

    assert converted["gain"] == pytest.approx(2.0)
    assert converted["integral_time_s"] == pytest.approx(120.0)


def test_gain_minutes_form_converts_the_integral_time_to_minutes() -> None:
    converted = convert_pi(PiSettings(kc=2.0, ti_s=120.0), form="gain_minutes")

    assert converted["gain"] == pytest.approx(2.0)
    assert converted["integral_time_min"] == pytest.approx(2.0)


def test_proportional_band_minutes_form_inverts_the_gain_into_a_band_in_percent() -> None:
    converted = convert_pi(PiSettings(kc=2.0, ti_s=120.0), form="proportional_band_minutes")

    assert converted["proportional_band_pct"] == pytest.approx(50.0)
    assert converted["integral_time_min"] == pytest.approx(2.0)


def test_gain_repeats_per_minute_form_inverts_the_integral_time_into_repeats() -> None:
    converted = convert_pi(PiSettings(kc=2.0, ti_s=120.0), form="gain_repeats_per_minute")

    assert converted["gain"] == pytest.approx(2.0)
    assert converted["repeats_per_min"] == pytest.approx(0.5)


def test_an_unknown_conversion_form_is_rejected() -> None:
    with pytest.raises(ValueError):
        convert_pi(PiSettings(kc=2.0, ti_s=120.0), form="stones_and_pounds")  # type: ignore[arg-type]


def test_a_model_with_a_non_positive_gain_is_rejected() -> None:
    with pytest.raises(ValueError):
        FopdtModel(gain=0.0, time_constant_s=100.0, delay_s=10.0)


def test_a_model_with_a_non_positive_time_constant_is_rejected() -> None:
    with pytest.raises(ValueError):
        FopdtModel(gain=2.0, time_constant_s=0.0, delay_s=10.0)


def test_a_model_with_a_non_positive_delay_is_rejected() -> None:
    with pytest.raises(ValueError):
        FopdtModel(gain=2.0, time_constant_s=100.0, delay_s=0.0)


def test_settings_with_a_non_positive_gain_are_rejected() -> None:
    with pytest.raises(ValueError):
        PiSettings(kc=0.0, ti_s=120.0)


def test_settings_with_a_non_positive_integral_time_are_rejected() -> None:
    with pytest.raises(ValueError):
        PiSettings(kc=2.0, ti_s=0.0)


def test_a_non_positive_tau_c_is_rejected() -> None:
    with pytest.raises(ValueError):
        simc_pi(SIMC_EXAMPLE_MODEL, tau_c_s=0.0)


def test_a_robustness_below_zero_is_rejected() -> None:
    with pytest.raises(ValueError):
        lambda_from_robustness(SIMC_EXAMPLE_MODEL, robustness=-0.1)


def test_a_robustness_above_one_is_rejected() -> None:
    with pytest.raises(ValueError):
        lambda_from_robustness(SIMC_EXAMPLE_MODEL, robustness=1.1)
