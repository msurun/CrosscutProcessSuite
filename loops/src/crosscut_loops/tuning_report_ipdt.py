"""PI tuning report for an integrating (level) loop from one open-loop record.

Identifies an integrator with dead time (``identification_ipdt``), applies the SIMC integrating
rule (``tuning_rules_integrating``) and attaches the DCS forms and vendor blocks exactly as the
FOPDT report does. A refused fit gives a report without settings and the refusal codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from crosscut_loops.identification_ipdt import IpdtFit, IpdtIdentificationError, identify_ipdt
from crosscut_loops.tuning_report import (
    LOW_CONFIDENCE_PREFIX,
    STICTION_BLOCKED_REASON,
    _dcs_forms,
    _format_number,
    _render_vendor_section,
)
from crosscut_loops.tuning_rules import ConversionForm, PiSettings
from crosscut_loops.tuning_rules_integrating import (
    lambda_from_robustness_integrating,
    simc_pi_integrating,
    tau_c_for_max_swing,
)
from crosscut_loops.vendor_forms import DEFAULT_OUT_SPAN, VendorSummary, vendor_summaries

REFUSED_CODE = "ipdt_refused"
SIEMENS_KEY = "siemens_pid_compact"
INVERT_TAG = "Config.InvertControl"
INVALID_SIGNALS = "invalid_signals"
INVALID_MODEL = "invalid_model"


@dataclass
class IpdtTuningReport:
    """Result of the integrating-loop tuning: fit, SIMC settings, forms and notes.

    ``invert_control`` (the Siemens ``Config.InvertControl`` meaning) is True for a negative slope
    (OUT up makes PV fall), i.e. a direct-acting controller; the FOPDT path always has False.
    ``blocked_code`` is None, ``"ipdt_refused"``, ``"stiction"`` or ``"model_failed"`` (malformed
    signals); ``blocked_reasons`` lists the reason codes.
    """

    loop_name: str
    fit: IpdtFit | None
    simc: PiSettings | None = None
    tau_c_s: float | None = None
    invert_control: bool = False
    dcs_forms: dict[ConversionForm, dict[str, float]] = field(default_factory=dict)
    vendor_forms: dict[str, VendorSummary] = field(default_factory=dict)
    robustness: float = 0.5
    blocked_code: str | None = None
    blocked_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_ipdt_report(
    loop_name: str,
    signals: tuple[np.ndarray, np.ndarray, np.ndarray],
    robustness: float,
    swing: tuple[float, float] | None = None,
    stiction: bool = False,
) -> IpdtTuningReport:
    """Identify the loop and compute SIMC settings; ``signals`` = (t_s, OUT, PV).

    ``swing`` = (max_swing in PV units, load_step_pct) selects tau_c from the swing limit instead
    of the robustness slider. ``stiction`` (suspected valve sticking) blocks the settings, as in
    the FOPDT report.
    """
    report = IpdtTuningReport(loop_name, None, robustness=robustness)
    try:
        fit = identify_ipdt(*signals)
    except IpdtIdentificationError as error:
        return _refuse(report, "model_failed", [INVALID_SIGNALS], str(error))
    report.fit = fit
    if stiction:
        return _refuse(report, "stiction", ["stiction"], STICTION_BLOCKED_REASON)
    if fit.verdict == "blocked":
        return _refuse(report, REFUSED_CODE, list(fit.reasons), "IPDT fit refused")
    return _tune(report, fit, swing)


def _refuse(
    report: IpdtTuningReport, code: str, reasons: list[str], text: str
) -> IpdtTuningReport:
    """Mark the report blocked: no settings, the reason codes and one note."""
    report.blocked_code, report.blocked_reasons = code, reasons
    report.notes.append(f"{text}: {', '.join(reasons)}")
    return report


def _tune(
    report: IpdtTuningReport, fit: IpdtFit, swing: tuple[float, float] | None
) -> IpdtTuningReport:
    """Settings from the fitted slope and delay; low confidence adds a note, never a block."""
    slope, delay = fit.model.slope_per_s, fit.model.delay_s
    try:
        if swing is None:
            tau_c = lambda_from_robustness_integrating(delay, report.robustness)
        else:
            tau_c = tau_c_for_max_swing(slope, delay, load_step_pct=swing[1], max_swing_pv=swing[0])
        simc = simc_pi_integrating(slope, delay, tau_c)
    except ValueError as error:
        return _refuse(report, REFUSED_CODE, [INVALID_MODEL], str(error))
    report.simc, report.tau_c_s, report.invert_control = simc, tau_c, slope < 0.0
    report.dcs_forms = _dcs_forms(simc)
    report.vendor_forms = _vendor_forms(simc, report.invert_control)
    if fit.verdict == "low_confidence":
        report.notes.append(LOW_CONFIDENCE_PREFIX + "; ".join(fit.reasons))
    return report


def _vendor_forms(simc: PiSettings, invert_control: bool) -> dict[str, VendorSummary]:
    """Vendor blocks as for FOPDT (no PV span known), with the Siemens action set."""
    forms = vendor_summaries(simc, None, DEFAULT_OUT_SPAN)
    forms[SIEMENS_KEY]["tags"][INVERT_TAG] = invert_control
    return forms


def render_ipdt_markdown(report: IpdtTuningReport) -> str:
    """Markdown of the integrating report: header, model, settings, vendor blocks, notes."""
    parts = [f"# Tuning report: {report.loop_name}\n"]
    if report.blocked_code is not None:
        parts.append(f"**Blocked:** {', '.join(report.blocked_reasons)}\n")
    parts.extend(_model_lines(report))
    parts.append(_render_vendor_section(report.vendor_forms, "## Vendor blocks"))
    if report.notes:
        notes = "\n".join(f"- {note}" for note in report.notes)
        parts.append(f"## Notes\n\n{notes}\n")
    return "\n".join(part for part in parts if part)


def _model_lines(report: IpdtTuningReport) -> list[str]:
    """Model and settings tables (integrating model: slope and dead time; SIMC only)."""
    if report.fit is None:
        return ["## Model\n\nNo model identified.\n"]
    model = report.fit.model
    lines = [
        "## Model (integrator with dead time)\n",
        "| Parameter | Value |",
        "| --- | --- |",
        f"| Slope (PV unit/s per % OUT) | {model.slope_per_s:.6g} |",
        f"| Dead time (s) | {_format_number(model.delay_s)} |",
        f"| R squared | {_format_number(report.fit.r_squared)} |",
        "",
    ]
    if report.simc is None:
        return [*lines, "## Settings\n\nNo settings computed.\n"]
    simc = report.simc
    return [
        *lines,
        "## Settings\n",
        "| Rule | Gain | Integral time (s) |",
        "| --- | --- | --- |",
        f"| SIMC (integrating) | {_format_number(simc.kc)} | {_format_number(simc.ti_s)} |",
        "",
        f"Action: {'direct' if report.invert_control else 'reverse'}-acting controller.\n",
    ]
