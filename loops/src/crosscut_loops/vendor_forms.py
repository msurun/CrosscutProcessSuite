"""Siemens and ABB PI parameter forms, with the evidence for each (assumption A7).

`tuning_rules.convert_pi` gives generic forms; this module says which vendor block uses which
form, what is checked against a public document and what is not, and turns a `PiSettings` into
the named parameters of that block. Tuning stays advisory: nothing here writes to a DCS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
            "Gain acts on PV in engineering units and output in output units (default 0..100): "
            "scale with pv_span / out_span (see siemens_gain)",
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


def siemens_gain(kc: float, pv_span: float, out_span: float = _PERCENT) -> float:
    """Return the PID_Compact Gain for a normalised kc.

    The SIMC/AMIGO kc is dimensionless: output fraction per PV fraction of range. PID_Compact
    multiplies the deviation in PV engineering units, so the range ratio enters the gain
    (principle: Siemens FAQ 109481448 section 1.4; the formula is ours, derived from it).

    Args:
        kc: Normalised controller gain.
        pv_span: Span of the process value in engineering units (e.g. 1000 for 0..1000 degC).
        out_span: Span of the output in output units (100 for the default 0..100 %).

    Returns:
        Gain in output units per PV engineering unit.
    """
    if pv_span <= 0.0 or out_span <= 0.0:
        raise ValueError("Spans must be positive")
    return kc * out_span / pv_span


def siemens_pid_compact(
    settings: PiSettings, pv_span: float, out_span: float = _PERCENT, reverse_acting: bool = False
) -> dict[str, float | bool]:
    """Name the PID_Compact instance-DB tags for a PI setting (PI only, TD = 0)."""
    return {
        "Retain.CtrlParams.Gain": siemens_gain(settings.kc, pv_span, out_span),
        "Retain.CtrlParams.Ti": settings.ti_s,
        "Retain.CtrlParams.Td": 0.0,
        "Retain.CtrlParams.PWeighting": 1.0,
        "Config.InvertControl": reverse_acting,
    }


def abb_pidcc(settings: PiSettings) -> dict[str, float]:
    """Name the PidCC parameters for a PI setting; TI is in seconds ONLY IF the unit is confirmed.

    Deviation is in percent of range on both sides, so the gain needs no scaling. The time unit
    is the open point of `VENDOR_FORMS["abb_pidcc"]`.
    """
    return {"Gain": settings.kc, "TI": settings.ti_s, "TD": 0.0}
