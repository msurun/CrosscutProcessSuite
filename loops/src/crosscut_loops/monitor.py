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
from crosscut_loops.stiction import detect_stiction


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
    stiction_verdict: str = "not_checked"


@dataclass(frozen=True)
class LoopSeries:
    """The caller-supplied series of one loop, before any per-sample filtering."""

    t_s: np.ndarray
    pv: np.ndarray
    sp: np.ndarray
    out: np.ndarray
    mode: np.ndarray
    quality: np.ndarray | None = None


@dataclass(frozen=True)
class LoopArrays:
    """Per-loop series and derived values that the draft report is built from."""

    pv: np.ndarray
    out: np.ndarray
    mode: np.ndarray
    active: np.ndarray
    error: np.ndarray
    n_samples: int
    harris: float
    period_s: float | None
    stiction: str


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


def _stiction_verdict(
    pv: np.ndarray, out: np.ndarray, dt_s: float, settings: LoopSettings
) -> str:
    """Stiction verdict for one uninterrupted AUTO stretch."""
    if len(pv) < settings.min_segment_samples or np.any(np.isnan(pv)) or np.any(np.isnan(out)):
        return "not_checked"
    try:
        return detect_stiction(pv, out, dt_s).verdict
    except ValueError:
        return "not_checked"


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
    if report.stiction_verdict == "stiction":
        found.append("stiction suspected: fix the valve before retuning the controller")
    return found


def _active_mask(
    pv: np.ndarray,
    sp: np.ndarray,
    mode: np.ndarray,
    quality: np.ndarray | None,
) -> np.ndarray:
    """Samples that count as "active": valid PV and SP, quality 0 when given, and outside MAN."""
    valid = ~np.isnan(pv) & ~np.isnan(sp)
    if quality is not None:
        valid &= quality == 0
    active: np.ndarray = valid & (mode != MAN)
    return active


def _mean_abs_or_zero(error: np.ndarray) -> float:
    """Mean absolute error, or 0.0 for an empty error series."""
    return float(np.mean(np.abs(error))) if len(error) else 0.0


def _std_or_zero(error: np.ndarray) -> float:
    """Standard deviation of the error, or 0.0 for an empty error series."""
    return float(np.std(error)) if len(error) else 0.0


def _count_mode_changes(mode: np.ndarray) -> int:
    """Number of times the controller mode switches between two consecutive samples."""
    return int(np.count_nonzero(mode[1:] != mode[:-1]))


def _build_draft(arrays: LoopArrays, settings: LoopSettings) -> LoopReport:
    """Assemble the unclassified report from the already-derived series metrics."""
    saturation = saturation_fraction(
        arrays.out[arrays.active], settings.out_low, settings.out_high
    )
    return LoopReport(
        n_samples=arrays.n_samples,
        service_factor=float(np.mean(arrays.active)),
        saturation_fraction=saturation,
        flatline_fraction=flatline_fraction(arrays.pv),
        mode_changes=_count_mode_changes(arrays.mode),
        mean_abs_error=_mean_abs_or_zero(arrays.error),
        error_std=_std_or_zero(arrays.error),
        harris_index=arrays.harris,
        oscillation_period_s=arrays.period_s,
        classification="",
        findings=[],
        stiction_verdict=arrays.stiction,
    )


def _longest_segment_metrics(
    series: LoopSeries, active: np.ndarray, settings: LoopSettings
) -> tuple[float, float | None, str]:
    """Harris index, oscillation period and stiction verdict of the longest active stretch."""
    dt_s = float(np.median(np.diff(series.t_s)))
    segment = _longest_run(active)
    harris, period_s = _segment_metrics((series.pv - series.sp)[segment], dt_s, settings)
    stiction = _stiction_verdict(series.pv[segment], series.out[segment], dt_s, settings)
    return harris, period_s, stiction


def _prepare_arrays(series: LoopSeries, settings: LoopSettings) -> LoopArrays:
    """Validate the series, pick the active samples and compute the stuck-out metrics."""
    active = _active_mask(series.pv, series.sp, series.mode, series.quality)
    harris, period_s, stiction = _longest_segment_metrics(series, active, settings)
    return LoopArrays(
        pv=series.pv,
        out=series.out,
        mode=series.mode,
        active=active,
        error=(series.pv - series.sp)[active],
        n_samples=len(series.t_s),
        harris=harris,
        period_s=period_s,
        stiction=stiction,
    )


# codecheck: allow too-many-parameters (public signature used by callers and tests)
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
    series = LoopSeries(t_s=t_s, pv=pv, sp=sp, out=out, mode=mode, quality=quality)
    draft = _build_draft(_prepare_arrays(series, settings), settings)
    classified = replace(draft, classification=_classify(draft, settings))
    return replace(classified, findings=_findings(classified, settings))
