"""Per-loop performance report: service factor, saturation, oscillation, Harris index, findings."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from crosscut_sim.core import MAN

from crosscut_loops.metrics import (
    flatline_fraction,
    hagglund_oscillation,
    harris_index,
    saturation_fraction,
)


@dataclass(frozen=True)
class LoopSettings:
    """Per-loop knowledge and thresholds; the first three have no sensible universal default."""

    delay_s: float  # process dead time, sets the Harris benchmark
    ultimate_period_s: float  # period of the loop's natural oscillation (Hagglund threshold)
    amplitude_limit: float  # acceptable oscillation amplitude, in PV units
    out_low: float = 0.0
    out_high: float = 100.0
    min_segment_samples: int = 200  # shortest AUTO stretch worth analysing
    harris_poor_threshold: float = 0.3
    saturation_limit: float = 0.2
    manual_limit: float = 0.5  # service factor below this means "the loop is not in use"
    flatline_limit: float = 0.05


@dataclass(frozen=True)
class LoopReport:
    """Result of :func:`analyze_loop`; ``harris_index`` is NaN when it could not be computed."""

    n_samples: int
    service_factor: float
    saturation_fraction: float
    flatline_fraction: float
    mode_changes: int
    mean_abs_error: float
    error_std: float
    harris_index: float
    oscillation_period_s: float | None
    classification: str
    findings: list[str]


def _longest_run(mask: np.ndarray) -> slice:
    """Slice covering the longest stretch of consecutive True values (empty if none)."""
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    starts, ends = edges[::2], edges[1::2]
    if len(starts) == 0:
        return slice(0, 0)
    best = int(np.argmax(ends - starts))
    return slice(int(starts[best]), int(ends[best]))


def _segment_metrics(
    error: np.ndarray, dt_s: float, settings: LoopSettings
) -> tuple[float, float | None]:
    """Harris index and oscillation period (None if none) of one uninterrupted AUTO stretch."""
    if len(error) < settings.min_segment_samples or np.var(error) == 0.0:
        return float("nan"), None
    delay_samples = max(1, round(settings.delay_s / dt_s))
    harris = harris_index(error, delay_samples)
    oscillation = hagglund_oscillation(
        error, dt_s, settings.amplitude_limit, settings.ultimate_period_s
    )
    return harris, oscillation.period_s


def _classify(report: LoopReport, settings: LoopSettings) -> str:
    """Name the most important problem of the loop; the order is the order of urgency."""
    if report.service_factor < settings.manual_limit:
        return "manual"
    if report.saturation_fraction > settings.saturation_limit:
        return "saturated"
    if report.oscillation_period_s is not None:
        return "oscillating"
    if report.harris_index < settings.harris_poor_threshold:
        return "poor_performance"
    return "ok"


def _findings(report: LoopReport, settings: LoopSettings) -> list[str]:
    """One English sentence per problem found, for the report."""
    found = []
    if report.flatline_fraction > settings.flatline_limit:
        found.append(
            f"flatline: {report.flatline_fraction:.0%} of PV samples are frozen "
            "(stuck sensor or lost data)"
        )
    messages = {
        "manual": f"manual: in use only {report.service_factor:.0%} of the time",
        "saturated": f"saturated: output at its limit {report.saturation_fraction:.0%} of the time",
        "oscillating": f"oscillating: sustained cycle of {report.oscillation_period_s} s period",
        "poor_performance": f"poor_performance: Harris index {report.harris_index:.2f}",
    }
    if report.classification in messages:
        found.append(messages[report.classification])
    return found


def analyze_loop(
    t_s: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    out: np.ndarray,
    mode: np.ndarray,
    *,
    quality: np.ndarray | None = None,
    settings: LoopSettings,
) -> LoopReport:
    """Analyse one loop from its time stamps, PV, SP, OUT and MODE (0 = MAN) series.

    Only samples with a valid PV/SP (and quality 0 when given) outside MAN count as "active";
    Harris index and oscillation use the longest uninterrupted active stretch, because the
    methods assume a continuous series.
    """
    valid = ~np.isnan(pv) & ~np.isnan(sp)
    if quality is not None:
        valid &= quality == 0
    active = valid & (mode != MAN)
    error = (pv - sp)[active]
    dt_s = float(np.median(np.diff(t_s)))
    segment = _longest_run(active)
    harris, period_s = _segment_metrics((pv - sp)[segment], dt_s, settings)
    draft = LoopReport(
        n_samples=len(t_s),
        service_factor=float(np.mean(active)),
        saturation_fraction=saturation_fraction(out[active], settings.out_low, settings.out_high),
        flatline_fraction=flatline_fraction(pv),
        mode_changes=int(np.count_nonzero(mode[1:] != mode[:-1])),
        mean_abs_error=float(np.mean(np.abs(error))) if len(error) else 0.0,
        error_std=float(np.std(error)) if len(error) else 0.0,
        harris_index=harris,
        oscillation_period_s=period_s,
        classification="",
        findings=[],
    )
    classified = replace(draft, classification=_classify(draft, settings))
    return replace(classified, findings=_findings(classified, settings))
