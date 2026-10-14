"""Siemens and ABB PI parameter forms, with the evidence for each (assumption A7).

`tuning_rules.convert_pi` gives generic forms (kc in output units per PV unit, as identified).
This module says which vendor block uses which form, what a public document confirms and what
not, and turns a `PiSettings` into the named parameters of that block. Tuning stays advisory:
nothing here writes to a DCS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from crosscut_loops.tuning_rules import ConversionForm, PiSettings

Evidence = Literal["verified", "partly_verified", "unverified"]

_PERCENT = 100.0


@dataclass(frozen=True)
class VendorForm:
    """One vendor block: its parameter form, the evidence level and the caveats.

    Attributes:
        key: Short identifier, e.g. "siemens_pid_compact".
        block: Vendor block name as the vendor writes it.
        form: Matching `ConversionForm` of `convert_pi`.
        evidence: How far a public document confirms the form.
        source: Document id, version and page (no copied text).
        caveats: Things the engineer must still check on the real system.
    """

    key: str
    block: str
    form: ConversionForm
    evidence: Evidence
    source: str
    caveats: tuple[str, ...]


class VendorSummary(TypedDict):
    """One vendor block as shown in a report: what to type, how sure we are, what to check."""

    block: str
    evidence: Evidence
    source: str
    tags: dict[str, float | bool]
    caveats: list[str]


VENDOR_FORMS: dict[str, VendorForm] = {
    "siemens_pid_compact": VendorForm(
        key="siemens_pid_compact",
        block="PID_Compact V2.x (S7-1200 FW>=4.0, S7-1500)",
        form="gain_seconds",
        evidence="verified",
        source=(
            "Siemens FAQ 109481448 V1.0 (01/2016) p.3-5: all times in seconds, no negative Gain; "
            "app. example 79047707 V3.0.0 (03/2017) p.14-15: y = Kp[(b w - x) + 1/(TI s)(w - x) "
            "+ TD s/(a TD s + 1)(c w - x)]; S7-1500 PID Control manual A5E35300227-AA 12/2014 "
            "p.90-91"
        ),
        caveats=(
            "Set PWeighting = 1.0 (b = 1), otherwise the setpoint is weighted and a step reacts "
            "slower than the textbook PI that SIMC and AMIGO assume",
            "TI = 0 switches the integral action OFF",
            "Gain must be positive; reverse action is Config.InvertControl",
            "Gain is entered in output units per PV engineering unit (raw, not normalised): the "
            "identified kc goes in as it is, but the same Gain on another range is another loop",
        ),
    ),
    "abb_pidcc": VendorForm(
        key="abb_pidcc",
        block="PidCC (AC 800M), documented through the Pid01A unit",
        form="gain_seconds",
        evidence="partly_verified",
        source=(
            "ABB 3AST001596D013 rev D (Pid01A, 2009) p.9-10, p.23: ideal PID, deviation in percent "
            "of range; ABB 3BSE041488-600 A (Binary and Analog Handling, 05/2016) p.120-124: "
            "G = Gain x OutRange / PvRange with Gain normalised and dimensionless, setpoint weight "
            "beta editable in PidCC; neither document states the unit of TI"
        ),
        caveats=(
            "Unit of TI and TD NOT confirmed by a document: check the PidCC page of the Control "
            "Builder library manual (3BSE035982) or the block's parameter help before use",
            "Pid01A is the ControlIT unit around PidCC, not the AC 800M library manual itself",
            "Gain is entered normalised (G = Gain x OutRange / PvRange is applied inside), "
            "so kc is used as it is, with no range scaling",
            "Reverse action is a selectable setting, not a negative Gain",
            "Setpoint weight beta is 0 for a discontinuous setpoint by default: set it to 1 "
            "(editable in PidCC) when an externally calculated tuning is applied",
        ),
    ),
}


def normalise_gain(kc: float, pv_span: float, out_span: float = _PERCENT) -> float:
    """Return the dimensionless gain G = kc * PvRange / OutRange.

    `kc` comes from identification on raw data, so it is in output units per PV unit
    (e.g. % valve per degC). ABB PidCC wants the normalised form (output fraction per PV
    fraction of range); Siemens PID_Compact wants the raw form (Siemens FAQ 109481448
    section 1.4 shows that the same Gain gives different loops on different ranges).

    Args:
        kc: Controller gain in output units per PV engineering unit.
        pv_span: Span of the process value in engineering units (e.g. 1000 for 0..1000 degC).
        out_span: Span of the output in output units (100 for a 0..100 % output).

    Returns:
        The gain with both ranges scaled to 1.
    """
    if pv_span <= 0.0 or out_span <= 0.0:
        raise ValueError("Spans must be positive")
    return kc * pv_span / out_span


def siemens_pid_compact(
    settings: PiSettings, reverse_acting: bool = False
) -> dict[str, float | bool]:
    """Name the PID_Compact instance-DB tags for a PI setting (PI only, TD = 0).

    `settings.kc` is in output units per PV engineering unit, which is what PID_Compact
    multiplies the deviation with, so it goes in as it is.
    """
    return {
        "Retain.CtrlParams.Gain": settings.kc,
        "Retain.CtrlParams.Ti": settings.ti_s,
        "Retain.CtrlParams.Td": 0.0,
        "Retain.CtrlParams.PWeighting": 1.0,
        "Config.InvertControl": reverse_acting,
    }


def abb_pidcc(settings: PiSettings, pv_span: float, out_span: float = _PERCENT) -> dict[str, float]:
    """Name the PidCC parameters for a PI setting; TI is in seconds ONLY IF the unit is confirmed.

    The entered Gain is normalised (the block applies OutRange / PvRange itself), so the ranges
    are needed. The time unit is the open point of `VENDOR_FORMS["abb_pidcc"]`.
    """
    return {"Gain": normalise_gain(settings.kc, pv_span, out_span), "TI": settings.ti_s, "TD": 0.0}


def vendor_summaries(
    settings: PiSettings, pv_span: float | None, out_span: float = _PERCENT
) -> dict[str, VendorSummary]:
    """Return every vendor form for the report: tags, evidence level, source and caveats.

    Without `pv_span` the ABB gain cannot be normalised, so its tags are empty and a caveat
    says why; the Siemens tags never need the ranges.
    """
    result: dict[str, VendorSummary] = {}
    for key, spec in VENDOR_FORMS.items():
        tags = _tags_for(key, settings, pv_span, out_span)
        caveats = list(spec.caveats)
        if tags is None:
            tags = {}
            caveats.insert(0, "PV range not given: the normalised Gain cannot be computed")
        result[key] = {
            "block": spec.block,
            "evidence": spec.evidence,
            "source": spec.source,
            "tags": tags,
            "caveats": caveats,
        }
    return result


def _tags_for(
    key: str, settings: PiSettings, pv_span: float | None, out_span: float
) -> dict[str, float | bool] | None:
    """Return the tags of one vendor, or None when the ranges needed for it are missing."""
    if key == "siemens_pid_compact":
        return siemens_pid_compact(settings)
    if pv_span is None:
        return None
    return dict(abb_pidcc(settings, pv_span, out_span))
