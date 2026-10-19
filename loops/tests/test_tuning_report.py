"""Tests for the tuning report builder that turns plant data into PI settings."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# The helper simulate_fopdt lives next to this package's tests, so we make that
# directory importable before importing it.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crosscut_loops.tuning_report import TuningReport, build_tuning_report, render_markdown
from test_identification import SimulationSettings, simulate_fopdt

GAIN = 2.0
TIME_CONSTANT_S = 30.0
DELAY_S = 8.0
IDENTIFIED_GAIN_TOLERANCE = 0.05  # 5 % relative error allowed
NOISE_SAMPLE_COUNT = 3000
NOISE_SEED = 7
DCS_FORM_NAMES = [
    "gain_seconds",
    "gain_minutes",
    "proportional_band_minutes",
    "gain_repeats_per_minute",
]
MODEL_FAILURE_PREFIX = "model identification failed"
STICTION_REASON = "stiction suspected: repair the valve before retuning"


def make_open_loop_data() -> tuple[np.ndarray, np.ndarray]:
    """Return (u, y) from a simulated FOPDT process with known parameters."""
    return simulate_fopdt(GAIN, TIME_CONSTANT_S, DELAY_S, SimulationSettings(seed=1))


def make_white_noise_data() -> tuple[np.ndarray, np.ndarray]:
    """Return (u, y) of pure white noise, which no FOPDT model can explain."""
    rng = np.random.default_rng(NOISE_SEED)
    controller_output = rng.normal(size=NOISE_SAMPLE_COUNT)
    process_value = rng.normal(size=NOISE_SAMPLE_COUNT)
    return controller_output, process_value


def build_report_for_open_loop(
    robustness: float = 0.5,
    stiction_verdict: str | None = None,
) -> TuningReport:
    """Build a report from the standard simulated process, with optional overrides."""
    controller_output, process_value = make_open_loop_data()
    return build_tuning_report(
        "FIC101",
        controller_output,
        process_value,
        1.0,
        robustness=robustness,
        stiction_verdict=stiction_verdict,
    )


def test_a_simulated_process_recovers_its_gain_and_is_not_blocked() -> None:
    """The report model carries the true process gain within 5 percent and is not blocked."""
    report = build_report_for_open_loop()

    assert report.blocked_reason is None
    assert report.model is not None
    assert abs(report.model.gain - GAIN) / GAIN <= IDENTIFIED_GAIN_TOLERANCE


def test_a_simulated_process_yields_positive_pi_settings() -> None:
    """Both SIMC and AMIGO must return usable positive PI settings for a healthy process."""
    report = build_report_for_open_loop()

    assert report.simc is not None
    assert report.simc.kc > 0
    assert report.amigo is not None
    assert report.amigo.ti_s > 0


def test_a_healthy_loop_is_not_blocked() -> None:
    """A healthy loop must not carry a blocked reason, otherwise good results are hidden from
    the user."""
    report = build_report_for_open_loop()

    assert report.blocked_reason is None


def test_all_dcs_form_names_are_present_in_the_report() -> None:
    """Every DCS parameter convention must be present, since users enter settings in their own
    vendor form."""
    report = build_report_for_open_loop()

    assert set(report.dcs_forms.keys()) == set(DCS_FORM_NAMES)


def test_a_higher_robustness_gives_a_lower_simc_gain() -> None:
    """Raising robustness must make SIMC more conservative (lower Kc), the main tuning knob."""
    aggressive = build_report_for_open_loop(robustness=0.0)
    conservative = build_report_for_open_loop(robustness=1.0)

    assert aggressive.simc is not None
    assert conservative.simc is not None
    assert conservative.simc.kc < aggressive.simc.kc


def test_suspected_stiction_blocks_the_report_with_the_repair_message() -> None:
    """A stiction verdict must block retuning with the repair message, because tuning cannot
    fix a sticking valve."""
    report = build_report_for_open_loop(stiction_verdict="stiction")

    assert report.blocked_reason == STICTION_REASON


def test_suspected_stiction_still_returns_pi_settings() -> None:
    """Even when blocked, the settings stay available so an expert can still inspect them."""
    report = build_report_for_open_loop(stiction_verdict="stiction")

    assert report.simc is not None


def test_white_noise_data_cannot_be_identified() -> None:
    """Data with no dynamics must give no model and no settings instead of invented ones."""
    controller_output, process_value = make_white_noise_data()

    report = build_tuning_report("FIC101", controller_output, process_value, 1.0)

    assert report.model is None
    assert report.simc is None


def test_white_noise_data_reports_an_identification_failure() -> None:
    """A failed identification must be explained through a blocked reason with the failure
    prefix."""
    controller_output, process_value = make_white_noise_data()

    report = build_tuning_report("FIC101", controller_output, process_value, 1.0)

    assert report.blocked_reason is not None
    assert report.blocked_reason.startswith(MODEL_FAILURE_PREFIX)


def test_markdown_of_a_healthy_report_names_the_loop_and_is_unblocked() -> None:
    """The Markdown of a healthy report must name the loop and show no Blocked marker."""
    report = build_report_for_open_loop()

    markdown = render_markdown(report)

    assert "# Tuning report: FIC101" in markdown
    assert "Blocked" not in markdown


def test_markdown_of_a_stiction_report_shows_the_blocked_reason() -> None:
    """The Markdown of a blocked report must show the blocked reason to the reader."""
    report = build_report_for_open_loop(stiction_verdict="stiction")

    markdown = render_markdown(report)

    assert "**Blocked:**" in markdown
    assert STICTION_REASON in markdown


def test_markdown_of_a_failed_identification_is_blocked() -> None:
    """A report whose identification failed must also render as blocked in Markdown."""
    controller_output, process_value = make_white_noise_data()
    report = build_tuning_report("FIC101", controller_output, process_value, 1.0)

    markdown = render_markdown(report)

    assert "**Blocked:**" in markdown
