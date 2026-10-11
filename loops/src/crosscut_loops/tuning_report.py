"""Build a PI tuning report from plant data, with DCS forms and Markdown output.

The report bundles everything a control engineer needs to retune a loop:

* the identified FOPDT model (if any),
* PI settings from the SIMC and AMIGO rules,
* the same settings expressed in several vendor (DCS) parameter forms,
* notes about data quality, and
* a blocking reason when the loop must not be retuned.

The module is a thin orchestrator: identification and tuning live in
``crosscut_loops.identification`` and ``crosscut_loops.tuning_rules``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from crosscut_loops.identification import identify_fopdt
from crosscut_loops.tuning_rules import (
    ConversionForm,
    FopdtModel,
    PiSettings,
    amigo_pi,
    convert_pi,
    lambda_from_robustness,
    simc_pi,
)

# The largest dead time to scan during identification, in seconds. Chosen as a
# fraction of the record length in samples priced below.
MAX_DELAY_FRACTION_OF_RECORD = 0.25

# Fallback sampling period, in seconds, when the caller does not know it.
DEFAULT_SAMPLE_TIME_S = 1.0

# Default robustness slider position: 0 is fast, 1 is robust.
DEFAULT_ROBUSTNESS = 0.5

# Preferred DCS parameter forms, in the order they appear in the report.
DCS_FORM_NAMES: tuple[ConversionForm, ...] = (
    "gain_seconds",
    "gain_minutes",
    "proportional_band_minutes",
    "gain_repeats_per_minute",
)

# Verdict strings accepted by ``build_tuning_report``.
STICTION_VERDICT = "stiction"

# Blocking messages shown when a loop must not be retuned as-is.
STICTION_BLOCKED_REASON = "stiction suspected: repair the valve before retuning"
MODEL_FAILURE_PREFIX = "model identification failed"

# Robustness values are clamped into this range before use.
MIN_ROBUSTNESS = 0.0
MAX_ROBUSTNESS = 1.0


@dataclass
class TuningReport:
    """Everything known about a loop after identification and tuning.

    Attributes:
        loop_name: Tag of the loop, e.g. ``"FIC101"``.
        model: Identified FOPDT model, or None when identification failed.
        simc: SIMC PI settings, or None when the model is unknown.
        amigo: AMIGO PI settings, or None when the model is unknown.
        dcs_forms: Converted settings per DCS form; empty when there is no model.
        robustness: Robustness slider used for the SIMC tuning rule.
        blocked_reason: Why the loop must not be retuned, or None when healthy.
        notes: Free-text observations gathered while building the report.
    """

    loop_name: str
    model: FopdtModel | None
    simc: PiSettings | None
    amigo: PiSettings | None
    dcs_forms: dict[ConversionForm, dict[str, float]] = field(default_factory=dict)
    robustness: float = DEFAULT_ROBUSTNESS
    blocked_reason: str | None = None
    notes: list[str] = field(default_factory=list)


def build_tuning_report(
    loop_name: str,
    u: np.ndarray,
    y: np.ndarray,
    dt_s: float = DEFAULT_SAMPLE_TIME_S,
    *,
    robustness: float = DEFAULT_ROBUSTNESS,
    stiction_verdict: str | None = None,
) -> TuningReport:
    """Identify a loop and compute its PI settings, DCS forms and notes.

    Identification failure does not raise: the report has no model and
    ``blocked_reason`` says why. Robustness is clamped to [0, 1].
    """
    robustness = _clamp_robustness(robustness)
    model, failure_reason = _identify_or_reason(u, y, dt_s)
    if model is None:
        return _unidentified_report(loop_name, failure_reason, robustness, stiction_verdict)
    return _identified_report(loop_name, model, robustness, stiction_verdict)


def _unidentified_report(
    loop_name: str,
    failure_reason: str | None,
    robustness: float,
    stiction_verdict: str | None,
) -> TuningReport:
    """Return the report for a loop whose model could not be identified."""
    return TuningReport(
        loop_name=loop_name,
        model=None,
        simc=None,
        amigo=None,
        robustness=robustness,
        blocked_reason=failure_reason,
        notes=_notes(stiction_verdict),
    )


def _identified_report(
    loop_name: str,
    model: FopdtModel,
    robustness: float,
    stiction_verdict: str | None,
) -> TuningReport:
    """Return the report for a loop with an identified model."""
    simc, amigo = _tune(model, robustness)
    return TuningReport(
        loop_name=loop_name,
        model=model,
        simc=simc,
        amigo=amigo,
        dcs_forms=_dcs_forms(simc),
        robustness=robustness,
        blocked_reason=_blocked_reason(stiction_verdict),
        notes=_notes(stiction_verdict),
    )


def _clamp_robustness(robustness: float) -> float:
    """Return robustness limited to the [0, 1] range."""
    return min(max(robustness, MIN_ROBUSTNESS), MAX_ROBUSTNESS)


def _max_delay_s(sample_count: int, dt_s: float) -> float:
    """Return the largest dead time to scan, in seconds.

    The cap keeps the scan short on long records while still allowing a delay
    of a quarter of the record.
    """
    max_delay_samples = max(1, int(MAX_DELAY_FRACTION_OF_RECORD * sample_count))
    return max_delay_samples * dt_s


def _identify_or_reason(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
) -> tuple[FopdtModel | None, str | None]:
    """Identify the model, returning (model, None) or (None, failure message).

    The identification error is caught on purpose: a report that cannot
    identify the loop is still useful, it just needs to say so.
    """
    try:
        model = identify_fopdt(
            controller_output, process_value, dt_s, _max_delay_s(len(controller_output), dt_s)
        )
    except ValueError as error:
        return None, f"{MODEL_FAILURE_PREFIX}: {error}"
    return model, None


def _tune(model: FopdtModel, robustness: float) -> tuple[PiSettings, PiSettings]:
    """Return the SIMC and AMIGO PI settings for the model."""
    tau_c_s = lambda_from_robustness(model, robustness)
    return simc_pi(model, tau_c_s), amigo_pi(model)


def _dcs_forms(simc: PiSettings) -> dict[ConversionForm, dict[str, float]]:
    """Return the SIMC settings converted into every DCS parameter form."""
    return {form: convert_pi(simc, form) for form in DCS_FORM_NAMES}


def _blocked_reason(stiction_verdict: str | None) -> str | None:
    """Return the reason that blocks a retune, or None when the loop is healthy."""
    if stiction_verdict == STICTION_VERDICT:
        return STICTION_BLOCKED_REASON
    return None


def _notes(stiction_verdict: str | None) -> list[str]:
    """Return free-text observations about the data and valve diagnosis."""
    notes: list[str] = []
    if stiction_verdict == STICTION_VERDICT:
        notes.append(STICTION_BLOCKED_REASON)
    return notes


def _format_number(value: float, decimals: int = 3) -> str:
    """Format a float for the report with a fixed number of decimals."""
    return f"{value:.{decimals}f}"


def _render_header(report: TuningReport) -> str:
    """Return the Markdown heading and the blocked line, if any."""
    lines = [f"# Tuning report: {report.loop_name}", ""]
    if report.blocked_reason is not None:
        lines.append(f"**Blocked:** {report.blocked_reason}")
        lines.append("")
    return "\n".join(lines)


def _render_model_section(report: TuningReport) -> str:
    """Return the Markdown section describing the identified model."""
    if report.model is None:
        return "## Model\n\nNo model identified.\n"
    model = report.model
    return (
        "## Model\n\n"
        "| Parameter | Value |\n"
        "| --- | --- |\n"
        f"| Gain | {_format_number(model.gain)} |\n"
        f"| Time constant (s) | {_format_number(model.time_constant_s)} |\n"
        f"| Dead time (s) | {_format_number(model.delay_s)} |\n"
    )


def _render_settings_section(report: TuningReport) -> str:
    """Return the Markdown section with the SIMC and AMIGO settings."""
    if report.simc is None or report.amigo is None:
        return "## Settings\n\nNo settings computed.\n"
    return (
        "## Settings\n\n"
        "| Rule | Gain | Integral time (s) |\n"
        "| --- | --- | --- |\n"
        f"| SIMC | {_format_number(report.simc.kc)} | {_format_number(report.simc.ti_s)} |\n"
        f"| AMIGO | {_format_number(report.amigo.kc)} | {_format_number(report.amigo.ti_s)} |\n"
    )


def _render_dcs_section(report: TuningReport) -> str:
    """Return the Markdown section listing the DCS parameter forms."""
    if not report.dcs_forms:
        return "## DCS forms\n\nNo DCS forms computed.\n"
    blocks = ["## DCS forms", ""]
    for form in DCS_FORM_NAMES:
        blocks.append(f"### {form}")
        blocks.append("")
        for key, value in report.dcs_forms[form].items():
            blocks.append(f"- {key}: {_format_number(value)}")
        blocks.append("")
    return "\n".join(blocks)


def _render_notes_section(report: TuningReport) -> str:
    """Return the Markdown section with the free-text notes, if any."""
    if not report.notes:
        return ""
    blocks = ["## Notes", ""]
    blocks.extend(f"- {note}" for note in report.notes)
    blocks.append("")
    return "\n".join(blocks)


def render_markdown(report: TuningReport) -> str:
    """Render a tuning report as Markdown.

    Args:
        report: The report to render.

    Returns:
        A Markdown document with a heading per report section.
    """
    sections = [
        _render_header(report),
        _render_model_section(report),
        _render_settings_section(report),
        _render_dcs_section(report),
        _render_notes_section(report),
    ]
    return "\n".join(section for section in sections if section)
