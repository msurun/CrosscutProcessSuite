"""Propose loop knowledge from history without saving engineering decisions.

Each editable value carries its source, time window and confidence for review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

import numpy as np

from crosscut_loops.history_windows import find_excitation_windows
from crosscut_loops.identification_ipdt import identify_ipdt
from crosscut_loops.identification_quality import (
    MIN_FREE_RUN_R2,
    assess_fit,
    count_excitation_events,
)
from crosscut_loops.loop_modes import AUTO, MAN
from crosscut_loops.oscillation_acf import acf_regularity, oscillation_reference
from crosscut_loops.tuning_report import identify_model

PERCENTILES = (1, 99)  # percent of observed samples
RANGE_PADDING = 0.10  # fraction of the central observed span, at each end
AMPLITUDE_FRACTION = 0.02  # fraction of the PV engineering span
MIN_FIT_SAMPLES = 60  # samples, matching the history window detector
RAMP_R2 = 0.98  # dimensionless linear-trend fit threshold
MIN_RAMP_TRAVEL = 1e-8  # PV engineering units; reject numerical roundoff
PHASE_ITERATIONS = 60  # bisections of the model phase-crossover frequency
UNIFORM_TOLERANCE = 0.01  # fraction of sample period allowed for grid jitter

Confidence = Literal["high", "medium", "low"]


class Evidence(TypedDict):
    """Traceable source of a candidate value; window timestamps are seconds."""

    kind: str
    window: list[float] | None
    events: int
    detail: str


class Proposal(TypedDict):
    """One editable value with enough evidence to accept or reject it."""

    value: float | str | None
    evidence: Evidence
    confidence: Confidence


@dataclass(frozen=True)
class _History:
    """Aligned, finite PV/OUT samples on a uniform grid measured in seconds."""

    time_s: np.ndarray
    process_value: np.ndarray
    setpoint: np.ndarray
    output: np.ndarray
    mode: np.ndarray

    @property
    def period_s(self) -> float:
        """Return the sampling interval in seconds."""
        return float(np.median(np.diff(self.time_s)))


def _proposal(value: float | str | None, evidence: Evidence,
              confidence: Confidence = "low") -> Proposal:
    return {"value": value, "evidence": evidence, "confidence": confidence}


def _evidence(kind: str, detail: str, history: _History | None = None,
              events: int = 0) -> Evidence:
    window = None if history is None else [float(history.time_s[0]), float(history.time_s[-1])]
    return {"kind": kind, "window": window, "events": events, "detail": detail}


# codecheck: allow too-many-parameters (issue #213 specifies this public interface)
def propose_knowledge(t_s: np.ndarray, pv: np.ndarray, sp: np.ndarray, out: np.ndarray,
                      mode: np.ndarray, tags_meta: dict) -> dict[str, Proposal | bool]:
    """Return reviewable knowledge and needs_step_test; raise ValueError for bad sampling.

    MODE uses repository codes MAN=0/AUTO=1; unknown MODE never licenses a step fit.
    Metadata maps pv/out to engineering tag rows and may include a vendor string.
    """
    history = _History(*(np.asarray(values, dtype=float) for values in (t_s, pv, sp, out, mode)))
    _validate_history(history)
    proposals = _range_proposals(history, tags_meta)
    proposals.update(_default_proposals(history, proposals, tags_meta))
    dynamics = _identify_history(history)
    proposals.update(dynamics)
    if not dynamics:
        proposals.update(_oscillation_proposal(history))
    return {**proposals, "needs_step_test": not bool(dynamics)}


def _validate_history(history: _History) -> None:
    arrays = (history.time_s, history.process_value, history.setpoint, history.output, history.mode)
    if any(values.ndim != 1 or values.shape != history.time_s.shape for values in arrays):
        raise ValueError("Provide equal-length one-dimensional time, PV, SP, OUT and MODE arrays")
    if history.time_s.size < 2:
        raise ValueError("Provide at least two history samples")
    if not all(np.all(np.isfinite(values)) for values in arrays[:2] + (history.output,)):
        raise ValueError("Provide finite time, PV and OUT; select a contiguous valid window")
    intervals = np.diff(history.time_s)
    if np.any(intervals <= 0) or not np.allclose(intervals, history.period_s,
                                               rtol=UNIFORM_TOLERANCE, atol=0):
        raise ValueError("Resample history to a strictly increasing, uniform time grid in seconds")


def _range_proposals(history: _History, metadata: dict) -> dict[str, Proposal]:
    proposals = {}
    for role, values in (("pv", history.process_value), ("out", history.output)):
        lower, upper = np.percentile(values, PERCENTILES)
        padding = RANGE_PADDING * (upper - lower)
        for bound, observed in (("min", lower - padding), ("max", upper + padding)):
            supplied = metadata.get(role, {}).get(f"eng_{bound}")
            is_supplied = isinstance(supplied, (int, float)) and np.isfinite(supplied)
            evidence = _evidence("tag_metadata", "Tag engineering limit") if is_supplied else (
                _evidence("observed_percentiles",
                          "1st/99th percentiles widened 10% per end", history))
            proposals[f"{role}_eng_{bound}"] = _proposal(
                float(supplied if is_supplied else observed), evidence,
                "high" if is_supplied else "low")
    return proposals


def _default_proposals(history: _History, ranges: dict, metadata: dict) -> dict[str, Proposal]:
    unknown = _evidence("unavailable", "No usable step fit; record an independent step test")
    span = ranges["pv_eng_max"]["value"] - ranges["pv_eng_min"]["value"]
    vendor = metadata.get("vendor")
    # Amplitude is an operational requirement, not a property identifiable from history.
    amplitude = _proposal(float(AMPLITUDE_FRACTION * span), _evidence(
        "starting_value", "2% of PV range; must be confirmed as a process requirement"))
    return {"delay_s": _proposal(None, unknown), "ultimate_period_s": _proposal(None, unknown),
            "process_kind": _ramp_proposal(history), "amplitude_limit": amplitude,
            "vendor": _proposal(vendor, _evidence("tag_metadata", "PID vendor metadata")
                                if vendor else _evidence("unavailable", "Confirm PID vendor"),
                                "high" if vendor else "low")}


def _slice_history(history: _History, rows: slice) -> _History:
    return _History(*(values[rows] for values in (history.time_s, history.process_value,
                                                 history.setpoint, history.output, history.mode)))


def _mode_segments(history: _History, mode_code: int) -> list[_History]:
    # Never concatenate separated MAN intervals: that would invent an unrecorded input step.
    selected = history.mode == mode_code
    edges = np.diff(np.concatenate(([False], selected, [False])).astype(int))
    return [_slice_history(history, slice(start, stop))
            for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1),
                                   strict=True) if stop - start >= MIN_FIT_SAMPLES]


def _identify_history(history: _History) -> dict[str, Proposal]:
    for segment in _mode_segments(history, MAN):
        if count_excitation_events(segment.output):
            result = _fit_segment(segment, "manual_out_step")
            if result:
                return result
    for segment in _mode_segments(history, AUTO):
        if not np.all(np.isfinite(segment.setpoint)) or np.ptp(segment.setpoint) == 0:
            continue
        for window in find_excitation_windows(segment.setpoint, segment.process_value,
                                               segment.period_s):
            result = _fit_segment(_slice_history(segment, slice(window.start, window.stop)),
                                  "auto_sp_step")
            if result:
                return result
    return {}


def _fit_segment(history: _History, kind: str) -> dict[str, Proposal]:
    if not count_excitation_events(history.output):
        return {}
    # IPDT: y=y0+beta*t+k*integral(u(t-theta)-u0)dt. Its R2 includes baseline drift;
    # accept integration only when the held-output tail also remains a near-linear ramp.
    integrating = identify_ipdt(history.time_s, history.output, history.process_value)
    if integrating.verdict != "blocked" and _has_ramp_tail(history):
        confidence: Confidence = "high" if integrating.verdict == "ok" else "low"
        evidence = _evidence(kind, f"IPDT R2={integrating.r_squared:.3f}; "
                             + "; ".join(integrating.reasons), history,
                             count_excitation_events(history.output))
        return _dynamic_proposals(integrating.model.delay_s, "integrating",
                                  4 * integrating.model.delay_s, (evidence, confidence))
    return _fit_fopdt(history, kind)


def _fit_fopdt(history: _History, kind: str) -> dict[str, Proposal]:
    model = identify_model(history.output, history.process_value, history.period_s)
    if model is None:
        return {}
    assessment = assess_fit(model, history.output, history.process_value, history.period_s)
    if assessment.free_run_r2 < MIN_FREE_RUN_R2:
        return {}
    is_uncertain = assessment.low_confidence or kind == "auto_sp_step"
    confidence: Confidence = "low" if is_uncertain else "high"
    evidence = _evidence(kind, f"FOPDT free-run R2={assessment.free_run_r2:.3f}; "
                         + "; ".join(assessment.reasons), history, assessment.excitation_events)
    # G(s)=K exp(-theta*s)/(tau*s+1): phase=-pi when atan(omega*tau)+omega*theta=pi.
    # Tu=2*pi/omega has seconds; this is a model estimate, not a measured ultimate cycle.
    period_s = _ultimate_period(model.time_constant_s, model.delay_s)
    return _dynamic_proposals(model.delay_s, "self_regulating", period_s, (evidence, confidence))


def _ultimate_period(time_constant_s: float, delay_s: float) -> float:
    lower, upper = 0.0, np.pi / delay_s
    for _ in range(PHASE_ITERATIONS):
        frequency = (lower + upper) / 2
        if np.arctan(frequency * time_constant_s) + frequency * delay_s < np.pi:
            lower = frequency
        else:
            upper = frequency
    return float(2 * np.pi / ((lower + upper) / 2))


def _dynamic_proposals(delay_s: float, process_kind: str, period_s: float,
                       source: tuple[Evidence, Confidence]) -> dict[str, Proposal]:
    evidence, confidence = source
    period_evidence = {**evidence, "detail": evidence["detail"]
                       + "; phase-crossover model estimate; confirm ultimate period"}
    return {"delay_s": _proposal(delay_s, evidence, confidence),
            "process_kind": _proposal(process_kind, evidence, confidence),
            "ultimate_period_s": _proposal(period_s if period_s > 0 else None,
                                            period_evidence, "low")}


def _has_ramp_tail(history: _History) -> bool:
    tail = slice(history.time_s.size // 2, None)
    times, values = history.time_s[tail], history.process_value[tail]
    if np.ptp(history.output[tail]) > MIN_RAMP_TRAVEL or np.ptp(values) < MIN_RAMP_TRAVEL:
        return False
    # Least squares y=a*t+b tests constant slope; R2=1-SSE/SST is dimensionless.
    predicted = np.polyval(np.polyfit(times - times[0], values, 1), times - times[0])
    total = np.sum((values - np.mean(values)) ** 2)
    return bool(1 - np.sum((values - predicted) ** 2) / total >= RAMP_R2)


def _ramp_proposal(history: _History) -> Proposal:
    if _has_ramp_tail(history):
        return _proposal("integrating", _evidence("held_output_ramp",
                         "Near-constant PV slope at held OUT; confirm with an OUT step", history))
    return _proposal("self_regulating", _evidence("unavailable",
                     "Default hypothesis; no usable excitation establishes process kind"))


def _oscillation_proposal(history: _History) -> dict[str, Proposal]:
    if not np.all(np.isfinite(history.setpoint)):
        return {}
    error = history.process_value - history.setpoint
    reference = oscillation_reference(error, history.process_value) if error.size >= 10 else None
    oscillation = acf_regularity(error, history.period_s, reference=reference)
    if not oscillation.regular:
        return {}
    return {"ultimate_period_s": _proposal(oscillation.period_s, _evidence(
        "pv_sp_autocorrelation", "Sustained PV-SP cycle; not proof of an ultimate cycle; confirm",
        history, int((history.time_s[-1] - history.time_s[0]) / oscillation.period_s)))}
