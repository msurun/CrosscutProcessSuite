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

# The largest dead time to scan during identification, as a fraction of the
# record length in samples. A quarter of the record keeps the scan short.
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

# Decimals used when formatting floats in the Markdown report.
REPORT_DECIMALS = 3


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


# codecheck: allow too-many-parameters (public signature used by callers and tests)
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

    A "loop" is one control loop of a plant, e.g. the temperature of a reactor:
    ``u`` is the controller output recorded over time (the manipulated
    variable, e.g. valve opening in %), ``y`` is the measurement it drives
    (e.g. reactor temperature in °C), and ``dt_s`` is the time between two
    consecutive samples in seconds.

    Identification failure does not raise: the report has no model and
    ``blocked_reason`` says why. Robustness is clamped to [0, 1].
    """
    # Robustness trades speed of response against tolerance to model error.
    # It arrives from a caller (config file, GUI slider) and could be any
    # number, so clamp it to [0, 1]: 0 = aggressive/tight, 1 = conservative.
    robustness = _clamp_robustness(robustness)
    # Fit the process model to the recorded step response. A failure is not an
    # exception but a reason string, because a bad window of data is expected
    # and should still produce a report the engineer can read.
    model, failure_reason = _identify_or_reason(u, y, dt_s)
    # No model means no PI settings can be computed; return the degraded report
    # that carries ``failure_reason`` in its ``blocked_reason`` field instead.
    if model is None:
        return _unidentified_report(loop_name, failure_reason, robustness, stiction_verdict)
    # Happy path: build the full report from the fitted model.
    return _identified_report(loop_name, model, robustness, stiction_verdict)


def _unidentified_report(
    loop_name: str,
    failure_reason: str | None,
    robustness: float,
    stiction_verdict: str | None,
) -> TuningReport:
    """Return the report for a loop whose model could not be identified.

    This is the failure path of tuning: no FOPDT/SOPDT model was fitted, so there
    is nothing to derive controller parameters from. The report still travels
    through the pipeline (and into the tuning report file) so the operator can see
    which loop failed and why, instead of the loop silently disappearing.

    Args:
        loop_name: Tag of the loop under study, taken from the input data. Printed
            as-is in the report and used to pair the loop with its symptoms.
        failure_reason: Human-readable explanation of why identification gave up,
            e.g. too few samples or a flat signal. Passed straight through as the
            report's ``blocked_reason``; ``None`` means the caller identified no
            specific cause and only knows the fit did not succeed.
        robustness: Stability margin of the loop as computed from the process data,
            a dimensionless ratio (typically the gain margin, where 1.0 is the
            stability limit and larger values are more robust). Reported even when
            no model exists, because it is measured, not derived from the model.
        stiction_verdict: Which stiction test, if any, flagged valve stiction; the
            verdict label, not a boolean. ``None`` when no test flagged anything.

    Returns:
        A :class:`TuningReport` for the loop, with ``model``, ``simc`` and
        ``amigo`` left ``None`` because no model or tuning rule could be applied.
    """
    return TuningReport(
        loop_name=loop_name,
        model=None,
        simc=None,
        amigo=None,
        robustness=robustness,
        # Why this loop has no controller parameters: the reason the model could
        # not be identified, surfaced to whoever reads the report.
        blocked_reason=failure_reason,
        # Stiction symptoms are collected independently of the model fit, so they
        # are still worth reporting on a loop that failed identification.
        notes=_notes(stiction_verdict),
    )


def _identified_report(
    loop_name: str,
    model: FopdtModel,
    robustness: float,
    stiction_verdict: str | None,
) -> TuningReport:
    """Return the report for a loop with an identified model.

    A loop is "identified" when its behaviour has been fitted to a FOPDT model, i.e. a
    First-Order Plus Dead Time model: a process gain, a time constant (how slowly the
    process reacts) and a dead time (how long before it reacts at all). With that model
    in hand we can compute controller tuning rules instead of guessing them.

    ``robustness`` is the tuning aggressiveness as a dimensionless factor in the
    robustness/performance trade-off: a larger value gives a more cautious controller
    that tolerates a more wrong model. ``stiction_verdict`` is the stiction detector's
    conclusion for this loop, or ``None`` when the detector was not run.

    Returns the :class:`TuningReport` assembled from both tuning rules.
    """
    # Each tuning rule is a pure calculation on the model plus the robustness factor.
    # SIMC and AMIGO are two well-known published PI/PID tuning methods; they usually
    # disagree slightly, so the report carries both and lets the engineer choose.
    simc, amigo = _tune(model, robustness)
    return TuningReport(
        loop_name=loop_name,
        model=model,
        simc=simc,
        amigo=amigo,
        # _dcs_forms restates the tuning in the parameter set the plant's distributed
        # control system (DCS) actually accepts: gain, integral time, derivative time
        # in the vendor's own units, rather than the abstract tuning-rule notation.
        dcs_forms=_dcs_forms(simc),
        robustness=robustness,
        # Stiction is valve sticking, which imitates oscillation and would otherwise make
        # the identified model misleading; if detected, the report is flagged as blocked
        # with that reason, and the notes explain the caveat to the reader.
        blocked_reason=_blocked_reason(stiction_verdict),
        notes=_notes(stiction_verdict),
    )


def _clamp_robustness(robustness: float) -> float:
    """Return robustness limited to the [0, 1] range."""
    return min(max(robustness, MIN_ROBUSTNESS), MAX_ROBUSTNESS)


def _max_delay_s(sample_count: int, dt_s: float) -> float:
    """Return the largest dead time to scan, in seconds.

    Used by the dead-time (paralysable pile-up) correction: we scan candidate
    dead times from zero up to this cap and pick the one that best fits the
    measured count-rate curve.

    The cap keeps the scan short on long records while still allowing a delay
    of a quarter of the record.

    Args:
        sample_count: number of samples in the record, in samples.
        dt_s: sampling interval of the record, in seconds per sample.

    Returns:
        The maximum dead time to consider, in seconds. Never zero: at least
        one sample wide.
    """
    # MAX_DELAY_FRACTION_OF_RECORD is a fraction of the record (dimensionless).
    # We convert it to a whole number of samples because the scan steps in
    # whole samples, and floor it with int(). max(1, ...) guarantees the cap
    # is at least one sample wide, otherwise a tiny record would give 0 s and
    # leave nothing to scan.
    max_delay_samples = max(1, int(MAX_DELAY_FRACTION_OF_RECORD * sample_count))
    # Samples -> seconds: each sample spans dt_s seconds.
    return max_delay_samples * dt_s


def _identify_or_reason(
    controller_output: np.ndarray,
    process_value: np.ndarray,
    dt_s: float,
) -> tuple[FopdtModel | None, str | None]:
    """Identify the model, returning (model, None) or (None, failure message).

    The loop under study is described by an FOPDT model: First-Order Plus
    Dead Time. It has three parameters: the process gain (how much the
    process value moves per unit of controller output), the time constant
    (seconds to reach ~63% of a step response, the "how sluggish" number)
    and the dead time (seconds of pure delay before the process reacts).

    ``controller_output`` and ``process_value`` are the two signals sampled
    together, same length, same sampling period ``dt_s`` in seconds.

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


def _format_number(value: float, decimals: int = REPORT_DECIMALS) -> str:
    """Format a float for the report with a fixed number of decimals."""
    return f"{value:.{decimals}f}"


def _render_header(report: TuningReport) -> str:
    """Return the Markdown heading and the blocked line, if any.

    A tuning report is the human-readable summary of one tuning loop run
    (loop_name identifies which loop). If the loop could not run to
    completion, blocked_reason says why, and the header warns the reader
    before they read any numbers that came out of a stopped run.
    """
    # Markdown lines in order; "" entries are blank separator lines that
    # keep the rendered heading apart from the following sections.
    lines = [f"# Tuning report: {report.loop_name}", ""]
    if report.blocked_reason is not None:
        lines.append(f"**Blocked:** {report.blocked_reason}")
        lines.append("")
    return "\n".join(lines)


def _render_model_section(report: TuningReport) -> str:
    """Return the Markdown section describing the identified model."""
    if report.model is None:
        return "## Model\n\nNo model identified.\n"
    return "\n".join(_model_section_lines(report.model))


def _model_section_lines(model: FopdtModel) -> list[str]:
    """Return the Markdown lines of the model table.

    The model is an FOPDT (first-order plus dead time) model: the process reaction
    curve is approximated by a single time constant in series with a transport delay.
    Its three parameters (gain, time constant, dead time) are printed here as a table.
    """
    # A Markdown table: the heading, the header row, the separator row, one row per
    # parameter, then a blank line so the next section starts on its own paragraph.
    # Gain is dimensionless (output units per input units); both times are in seconds.
    return [
        "## Model",
        "",
        "| Parameter | Value |",
        "| --- | --- |",
        f"| Gain | {_format_number(model.gain)} |",
        f"| Time constant (s) | {_format_number(model.time_constant_s)} |",
        f"| Dead time (s) | {_format_number(model.delay_s)} |",
        "",
    ]


def _render_settings_section(report: TuningReport) -> str:
    """Return the Markdown section with the SIMC and AMIGO settings."""
    if report.simc is None or report.amigo is None:
        return "## Settings\n\nNo settings computed.\n"
    return "\n".join(_settings_section_lines(report.simc, report.amigo))


def _settings_section_lines(simc: PiSettings, amigo: PiSettings) -> list[str]:
    """Return the Markdown lines of the tuning settings table.

    Both controllers are PI controllers, described by the same two parameters:
    ``kc`` is the proportional gain (dimensionless) and ``ti_s`` is the integral
    time (seconds). Each row of the table is one tuning rule applied to the
    same process. Values are rendered with ``_format_number`` so the table
    stays readable and columns line up. Returns the list of Markdown lines,
    including the header, the table header and separator row, one row per
    tuning rule, and a trailing blank line.
    """
    # A Markdown table needs a blank line before it, a header row, a separator
    # row that fixes the number of columns, then one row per data record.
    # The empty string at the end separates this table from the next section.
    return [
        "## Settings",
        "",
        "| Rule | Gain | Integral time (s) |",
        "| --- | --- | --- |",
        f"| SIMC | {_format_number(simc.kc)} | {_format_number(simc.ti_s)} |",
        f"| AMIGO | {_format_number(amigo.kc)} | {_format_number(amigo.ti_s)} |",
        "",
    ]


def _render_dcs_section(report: TuningReport) -> str:
    """Return the Markdown section listing the DCS parameter forms.

    DCS ("discrete control system", the run-to-run controller of a fab tool) is a
    model whose parameters are estimated separately for each "form" a user may
    want. This function renders one Markdown table per form.

    Returns the Markdown text, ending with a newline. Forms that were not
    estimated in the report are skipped silently.
    """
    # `dcs_forms` maps a form name to its estimated parameters. When the report
    # has no entries at all (nothing was computed), emit a placeholder section
    # so the document keeps its structure instead of an empty heading.
    if not report.dcs_forms:
        return "## DCS forms\n\nNo DCS forms computed.\n"

    # One string per Markdown line; `blocks` is later joined with newlines. The
    # trailing "" is the blank line that separates the heading from the tables.
    blocks = ["## DCS forms", ""]

    # Iterate over the canonical form order (not the dict order) so the output
    # is stable across runs regardless of insertion order in `dcs_forms`.
    for form in DCS_FORM_NAMES:
        # `_dcs_form_lines` returns the heading plus the rows of one form's
        # table; extend keeps the flat list-of-lines invariant of `blocks`.
        blocks.extend(_dcs_form_lines(form, report.dcs_forms[form]))

    return "\n".join(blocks)


def _dcs_form_lines(form: ConversionForm, values: dict[str, float]) -> list[str]:
    """Return the Markdown lines describing one DCS parameter form."""
    lines = [f"### {form}", ""]
    lines.extend(f"- {key}: {_format_number(value)}" for key, value in values.items())
    lines.append("")
    return lines


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

    Markdown is plain text where blank lines separate blocks and a line starting
    with ``#`` is a heading (``##`` is a sub-heading, and so on).

    Args:
        report: The report to render.

    Returns:
        A Markdown document with a heading per report section.
    """
    # Each renderer returns one section of the document. A renderer returns an
    # empty string when the report has nothing to say for that section, so an
    # empty string here means "this section is absent", not "an empty section".
    sections = [
        _render_header(report),
        _render_model_section(report),
        _render_settings_section(report),
        _render_dcs_section(report),
        _render_notes_section(report),
    ]
    # Drop the absent sections instead of emitting stray blank lines. Joining
    # with "\n" keeps every section a separate Markdown block.
    return "\n".join(section for section in sections if section)
