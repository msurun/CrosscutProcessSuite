"""Per-loop performance report: service factor, saturation, oscillation, Harris index, findings."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from crosscut_sim.core import MAN

from crosscut_loops.health_kpis import (
    QUANTISATION_LIMITING,
    quantisation_ratio,
    reversals_per_hour,
    valve_extremes,
    valve_travel_per_hour,
)
from crosscut_loops.metrics import (
    flatline_fraction,
    hagglund_oscillation,
    harris_index,
    saturation_fraction,
)
from crosscut_loops.oscillation_acf import acf_regularity
from crosscut_loops.stiction import detect_stiction
from crosscut_loops.stiction_suspicion import SuspicionResult, stiction_suspicion

MIN_STAMPS_FOR_PERIOD = 2
REVERSAL_MIN_MOVE_PERCENT = 0.1  # of output span; smaller output moves are not valve motion
MIN_KPI_SAMPLES = 50

# Per-loop knowledge a conclusion depends on. A conclusion whose knowledge is not in
# LoopSettings.known is reported as "not assessed" instead of being computed from a placeholder
# (exp18: placeholder ranges and limits flagged 42 of 44 real loops).
OUT_RANGE = "out_range"  # engineering range of OUT: saturation and valve KPIs
DELAY = "delay"  # process dead time: Harris index
OSCILLATION_LIMITS = "oscillation_limits"  # ultimate period and amplitude limit: Hagglund
KNOWN_ALL = frozenset({OUT_RANGE, DELAY, OSCILLATION_LIMITS})
# What is withheld when a piece of knowledge is missing, in the order not_assessed lists it.
WITHHELD_BY = (
    ("saturation", OUT_RANGE),
    ("valve_kpis", OUT_RANGE),
    ("harris", DELAY),
    ("oscillation_amplitude", OSCILLATION_LIMITS),  # cycles are still found by ACF regularity
)
OSC_HAGGLUND = "hagglund"
OSC_ACF = "acf"


@dataclass(frozen=True)
class LoopSettings:
    """Per-loop knowledge and thresholds; the first three have no sensible universal default.

    ``known`` names the fields that come from configuration rather than a placeholder; the
    default (all known) keeps callers that pass real values unchanged.
    """

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
    scan_period_s: float | None = None  # nominal logging period; overrides the estimate when set
    process_kind: str = "self_regulating"  # or "integrating" (level loop): picks the signal tested
    known: frozenset[str] = KNOWN_ALL  # subset of KNOWN_ALL backed by configuration


def not_assessed(settings: LoopSettings) -> tuple[str, ...]:
    """Conclusions withheld because the knowledge they need is not configured (fixed order)."""
    return tuple(name for name, needs in WITHHELD_BY if needs not in settings.known)


def sampling_period(t_s: np.ndarray, nominal_s: float | None = None) -> float:
    """Sampling period of a stretch of timestamps, in seconds per sample.

    Timestamp jitter makes the median step wander (it biased the Harris index by
    7-11 % in exp05).  The mean step (t_end - t_start) / (n - 1) is unaffected by
    jitter because the offsets cancel at the two ends.  The stretch must be free of
    logging gaps, which is true for one active segment; an explicit nominal period
    wins when the owner knows it.
    """
    if nominal_s is not None and nominal_s > 0.0:
        return float(nominal_s)
    if len(t_s) < MIN_STAMPS_FOR_PERIOD:
        raise ValueError("Need at least two timestamps to estimate a sampling period")
    return float((t_s[-1] - t_s[0]) / (len(t_s) - 1))


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
    stiction_suspicion: float | None = None  # ranked suspicion 0..1, None when not ranked
    stiction_advice: str = "not_checked"  # "test_valve", "unlikely", "not_ranked", "not_checked"
    valve_travel_per_h: float | None = None  # output movement, percent of span per hour (AUTO)
    valve_reversals_per_h: float | None = None  # output direction changes per hour (AUTO)
    out_quantisation_ratio: float | None = None  # output step / noise; >= 1 limits control
    valve_sizing_hint: str | None = None  # "oversized" / "undersized" from the median output
    not_assessed: tuple[str, ...] = ()  # conclusions withheld for missing knowledge (WITHHELD_BY)
    oscillation_method: str | None = None  # OSC_HAGGLUND or OSC_ACF when a cycle was found
    oscillation_regularity: float | None = None  # Thornhill r of the ACF method, else None


@dataclass(frozen=True)
class Oscillation:
    """Detected cycle of one stretch: period in seconds, method, ACF regularity (None if none)."""

    period_s: float | None = None
    method: str | None = None
    regularity: float | None = None


@dataclass(frozen=True)
class ValveKpis:
    """Valve wear and sizing numbers of the longest AUTO stretch; None when unavailable."""

    travel: float | None = None
    reversals: float | None = None
    quantisation: float | None = None
    sizing: str | None = None


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
    oscillation: Oscillation
    stiction: str
    suspicion: SuspicionResult
    valve: ValveKpis


def _longest_run(mask: np.ndarray) -> slice:
    """Slice covering the longest stretch of consecutive True values (empty if none).

    A "run" is a maximal block of adjacent True values, i.e. a contiguous group
    such as ``[False, True, True, False]`` -> the run covers indices 1-2.

    Returns a slice with no elements (``slice(0, 0)``) when the mask has no True.
    The slice bounds are indices into the original ``mask`` (unit: array position),
    so ``mask[result]`` selects exactly the longest run.
    """
    # A run starts where False -> True and ends where True -> False. Rather than
    # scanning the mask element by element, we detect those two transitions. The
    # padding puts a False on each side so that a run touching an array boundary
    # still produces both a start edge and an end edge.
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)

    # np.diff of a boolean step is -1 at a True -> False transition (run end)
    # and +1 at a False -> True transition (run start). flatnonzero gives the
    # positions of those transitions in the padded array.
    edges = np.flatnonzero(np.diff(padded))

    # Transitions come in pairs (start, end). Slicing with step 2 splits the flat
    # list of positions into the starts and the ends of every run. Invariant:
    # starts[i] < ends[i] for every i, and starts/ends have the same length.
    starts, ends = edges[::2], edges[1::2]

    if len(starts) == 0:
        return slice(0, 0)

    # ends - starts is the length of each run in elements; argmax picks the index
    # of the longest one (the first such index when there are ties).
    best = int(np.argmax(ends - starts))

    # Because of the one-element left padding, a transition position in `padded`
    # equals the index in `mask` for starts, and the exclusive end for ends.
    return slice(int(starts[best]), int(ends[best]))


def _segment_metrics(
    error: np.ndarray, dt_s: float, settings: LoopSettings
) -> tuple[float, Oscillation]:
    """Harris index and detected oscillation of one uninterrupted AUTO stretch.

    The stretch is the error signal recorded while the controller stayed in AUTO without
    interruption; its quality is summarised by two numbers:

    * the Harris index from :func:`harris_index`, a unitless ratio that compares the
      achieved control performance with the best performance a minimum-variance
      controller could reach on the same signal (1.0 means "nothing left to improve");
    * the oscillation: from :func:`hagglund_oscillation` when the loop's limits are configured,
      otherwise from the parameter-free ACF regularity test (:func:`acf_regularity`); its
      period is ``None`` when the stretch does not oscillate persistently.

    Returns a ``(harris, oscillation)`` pair, with ``harris`` set to ``nan`` when the
    stretch is too short or perfectly flat to say anything about it.

    Parameters
    ----------
    error:
        Error samples of the stretch (process variable minus setpoint), in engineering
        units. Its length is the number of samples at the sampling rate ``1 / dt_s``.
    dt_s:
        Sampling interval between two consecutive samples of ``error``, in seconds.
    settings:
        Loop tuning parameters; the ones used here are ``min_segment_samples`` (count),
        ``delay_s`` (seconds), ``amplitude_limit`` and ``ultimate_period_s``.
    """
    # Too few samples give no statistics, and a constant signal has no variance to
    # divide by: both cases make the Harris index undefined, so report nothing.
    if len(error) < settings.min_segment_samples or np.var(error) == 0.0:
        return float("nan"), Oscillation()
    return _harris_if_known(error, dt_s, settings), _oscillation(error, dt_s, settings)


def _harris_if_known(error: np.ndarray, dt_s: float, settings: LoopSettings) -> float:
    """Harris index of the stretch, or NaN when the dead time is not configured."""
    if DELAY not in settings.known:
        return float("nan")
    # The Harris index needs the dead time of the loop expressed as a whole number of
    # samples. Rounding the quotient delay_s / dt_s can give 0, but the algorithm needs
    # at least one sample of lag, hence the max(1, ...).
    delay_samples = max(1, round(settings.delay_s / dt_s))
    return harris_index(error, delay_samples)


def _oscillation(error: np.ndarray, dt_s: float, settings: LoopSettings) -> Oscillation:
    """Detected cycle: Hagglund with configured limits, else ACF regularity (Thornhill 2003)."""
    if OSCILLATION_LIMITS not in settings.known:
        found = acf_regularity(error, dt_s)
        return (
            Oscillation(found.period_s, OSC_ACF, found.regularity)
            if found.regular
            else Oscillation()
        )
    # Hagglund's method detects a sustained oscillation (limit cycle) and returns it
    # with its period; a stretch that does not oscillate yields period None.
    hagglund = hagglund_oscillation(
        error, dt_s, settings.amplitude_limit, settings.ultimate_period_s
    )
    return Oscillation(hagglund.period_s, OSC_HAGGLUND) if hagglund.detected else Oscillation()


def _stiction_verdict(pv: np.ndarray, out: np.ndarray, dt_s: float, settings: LoopSettings) -> str:
    """Stiction verdict for one uninterrupted AUTO stretch.

    Stiction is valve stick-slip: the controller output moves but the process
    variable stays put until the valve breaks free and jumps. ``detect_stiction``
    fits that behaviour and returns an object whose ``verdict`` field is a short
    label such as "stiction" or "no_stiction".

    Args:
        pv: Process variable samples, one per scan, in engineering units.
        out: Controller output samples, aligned index-by-index with ``pv``,
            in percent of output span.
        dt_s: Sampling interval between consecutive samples, in seconds.
        settings: Loop settings supplying ``min_segment_samples``, the shortest
            stretch of samples the detector can trust.

    Returns:
        The detector's verdict string, or "not_checked" when the stretch is too
        short, contains NaN samples, or the detector rejects the samples.
    """
    # Too few samples give a meaningless fit, and NaN samples break the
    # detector's sums, so both cases skip the check instead of guessing.
    if len(pv) < settings.min_segment_samples or np.any(np.isnan(pv)) or np.any(np.isnan(out)):
        return "not_checked"
    try:
        return detect_stiction(pv, out, dt_s).verdict
    # The detector raises ValueError when the samples do not fit its model;
    # that is a missing answer, not a crash, so report "not_checked".
    except ValueError:
        return "not_checked"


def _suspicion(
    series: LoopSeries, segment: slice, dt_s: float, settings: LoopSettings
) -> SuspicionResult:
    """Ranked stiction suspicion for one uninterrupted AUTO stretch.

    The suspicion needs a regular oscillation window inside the stretch; without one the loop
    is simply "not_ranked". Short stretches and NaN samples are "not_checked", as for the verdict.
    """
    pv, out, sp = series.pv[segment], series.out[segment], series.sp[segment]
    if len(pv) < settings.min_segment_samples or np.isnan([pv, out, sp]).any():
        return SuspicionResult(None, "not_checked", None, None, None, "stretch too short or NaN")
    kind = "L" if settings.process_kind == "integrating" else "F"
    return stiction_suspicion(sp, pv, out, dt_s, kind)


def _classify(report: LoopReport, settings: LoopSettings) -> str:
    """Name the most important problem of the loop; the order is the order of urgency.

    The first matching rule wins, so the checks below must stay in this order:
    a loop can be both manual and oscillating, but "manual" is what the
    operator has to fix first.

    Returns one of "manual", "saturated", "oscillating",
    "poor_performance" or "ok".
    """
    # Service factor (unitless, 0..1): share of samples that are active. Below manual_limit the
    # operator keeps taking the loop by hand, so its tuning is not the real problem yet.
    if report.service_factor < settings.manual_limit:
        return "manual"

    # Saturation fraction (unitless, 0..1): share of the time the controller
    # output sits pinned at its limit. While it is pinned the loop is open,
    # so no tuning verdict can be trusted.
    if report.saturation_fraction > settings.saturation_limit:
        return "saturated"

    # Oscillation period in seconds, or None when no sustained oscillation was
    # detected. Not None means the loop keeps cycling on its own, which is more
    # urgent than a merely sluggish response.
    if report.oscillation_period_s is not None:
        return "oscillating"

    # Harris index (dimensionless): the variance of a minimum-variance benchmark divided by the
    # loop's own variance; lower is worse, 1.0 is optimal. Below harris_poor_threshold the loop
    # is clearly underperforming (NaN, not computable, never counts as poor).
    if report.harris_index < settings.harris_poor_threshold:
        return "poor_performance"

    return "ok"


def _findings(report: LoopReport, settings: LoopSettings) -> list[str]:
    """Turn the numbers and labels computed for one control loop into plain-English problems.

    Each returned string is one finding a plant operator can read on its own; an empty list
    means no problem was detected. "PV" below is the process variable, the measurement that
    the controller is trying to hold at its setpoint.

    Returns:
        list[str]: one sentence per detected problem, in a fixed order (flatline first,
        then the loop classification, then stiction).
    """
    found = _flatline_findings(report, settings)
    found += _classification_findings(report)
    found += _stiction_findings(report)
    found += _valve_findings(report)
    return found


def _flatline_findings(report: LoopReport, settings: LoopSettings) -> list[str]:
    """Finding for a frozen PV: the transmitter is probably stuck or the data link is dead."""
    # flatline_fraction is a ratio in [0, 1]; no statistic of a frozen signal is trustworthy.
    if report.flatline_fraction > settings.flatline_limit:
        return [
            f"flatline: {report.flatline_fraction:.0%} of PV samples are frozen "
            "(stuck sensor or lost data)"
        ]
    return []


def _classification_findings(report: LoopReport) -> list[str]:
    """The sentence that belongs to the loop classification, if it names a problem."""
    messages = {
        # service_factor is the fraction of samples that are active (valid PV/SP, quality 0 when
        # given, and not MAN). It is a ratio in [0, 1] and is rendered as a percentage.
        "manual": f"manual: in use only {report.service_factor:.0%} of the time",
        # saturation_fraction is the share of time the controller output sits at its low or
        # high limit, i.e. the manipulated variable cannot move any further.
        "saturated": f"saturated: output at its limit {report.saturation_fraction:.0%} of the time",
        # oscillation_period_s is the period of the detected cycle in seconds; the '_s' suffix
        # denotes seconds.
        "oscillating": _oscillation_message(report),
        # harris_index is the ratio of the best achievable (minimum-variance) variance to the
        # variance the loop actually delivers. A value near 1 means the controller is close to
        # optimal; smaller values mean poor control.
        "poor_performance": f"poor_performance: Harris index {report.harris_index:.2f}",
    }
    return [messages[report.classification]] if report.classification in messages else []


def _stiction_findings(report: LoopReport) -> list[str]:
    """Finding for a diagnosed stiction, or for a weak suspicion that needs a valve test."""
    if report.stiction_verdict == "stiction":
        return ["stiction suspected: fix the valve before retuning the controller"]
    if report.stiction_advice == "test_valve":
        return [
            f"stiction possible (suspicion {report.stiction_suspicion:.2f}, a weak ranking): "
            "periodic upstream forcing can look the same; confirm with a valve test or a gain "
            "change (a stiction cycle changes period with the gain, a forced one does not) "
            "before retuning"
        ]
    return []


def _oscillation_message(report: LoopReport) -> str:
    """Oscillation finding; the ACF method finds regular cycles but cannot judge their size."""
    if report.oscillation_method != OSC_ACF:
        return f"oscillating: sustained cycle of {report.oscillation_period_s} s period"
    return (
        f"oscillating: regular cycle of {report.oscillation_period_s:.0f} s period "
        f"(ACF regularity {report.oscillation_regularity:.1f}); whether its amplitude is "
        "tolerable is not assessed without an amplitude limit; on fast noise without any "
        "cycle this method still reports one in up to 9 % of records of 1000+ samples "
        "(synthetic, exp24), so confirm the cycle on the trend"
    )


def _valve_findings(report: LoopReport) -> list[str]:
    """Findings from the valve KPIs: quantisation that limits control and valve sizing."""
    found = []
    ratio = report.out_quantisation_ratio
    if ratio is not None and ratio >= QUANTISATION_LIMITING:
        found.append(
            f"quantisation: output resolution is {ratio:.1f}x the noise level, which limits "
            "control and can look like stiction"
        )
    if report.valve_sizing_hint is not None:
        found.append(
            f"valve {report.valve_sizing_hint}: the output sits mostly "
            f"{'low' if report.valve_sizing_hint == 'oversized' else 'high'} in its range"
        )
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
    """Assemble the unclassified report from the already-derived series metrics.

    The report collects per-series statistics of a control loop: service factor, the fraction
    of time the controller output is saturated, the flatline fraction, the number of mode
    changes, the tracking error, the Harris index (1.0 means minimum-variance control), the
    oscillation period in seconds, the stiction verdict and suspicion, and the valve KPIs.
    Classification and findings stay empty here; a later stage fills them in.

    Returns a ``LoopReport`` with ``classification=""`` and ``findings=[]``.
    """
    valve = arrays.valve
    return replace(
        _series_report(arrays, settings),
        valve_travel_per_h=valve.travel,
        valve_reversals_per_h=valve.reversals,
        out_quantisation_ratio=valve.quantisation,
        valve_sizing_hint=valve.sizing,
        not_assessed=not_assessed(settings),
    )


def _series_report(arrays: LoopArrays, settings: LoopSettings) -> LoopReport:
    """The report fields that come from the series statistics (no valve KPIs yet)."""
    saturation = _saturation_of(arrays, settings)
    return LoopReport(
        n_samples=arrays.n_samples,
        service_factor=float(np.mean(arrays.active)),
        saturation_fraction=saturation,
        # Share of PV samples inside runs of identical values (a stuck sensor or lost data).
        flatline_fraction=flatline_fraction(arrays.pv),
        # Number of changes of the controller mode code between consecutive samples.
        mode_changes=_count_mode_changes(arrays.mode),
        # Mean of |error| over the active samples; 0.0 when there are none.
        mean_abs_error=_mean_abs_or_zero(arrays.error),
        # Standard deviation of the error, same 0.0-for-no-data convention.
        error_std=_std_or_zero(arrays.error),
        # Harris index, dimensionless; 1.0 = best achievable (minimum variance) control.
        harris_index=arrays.harris,
        # Dominant oscillation period in seconds, or None if no oscillation was found.
        oscillation_period_s=arrays.oscillation.period_s,
        oscillation_method=arrays.oscillation.method,
        oscillation_regularity=arrays.oscillation.regularity,
        # Left empty on purpose: the classifier that runs afterwards assigns the label.
        classification="",
        # Left empty on purpose: findings are appended by the later analysis stages.
        findings=[],
        stiction_verdict=arrays.stiction,
        stiction_suspicion=arrays.suspicion.score,
        stiction_advice=arrays.suspicion.advice,
    )


def _saturation_of(arrays: LoopArrays, settings: LoopSettings) -> float:
    """Share of active samples with OUT at a limit; NaN when the OUT range is unknown."""
    # Only ACTIVE samples count (arrays.active is a boolean mask): in MAN or with invalid
    # PV/SP the output is not the controller's, which would bias the fraction. out_low and
    # out_high are the limits of the OUT tag in its own units; the result is a fraction in [0, 1].
    return (
        saturation_fraction(arrays.out[arrays.active], settings.out_low, settings.out_high)
        if OUT_RANGE in settings.known
        else float("nan")  # unknown OUT range: "at the limit" has no meaning
    )


def _longest_segment_metrics(
    series: LoopSeries, active: np.ndarray, settings: LoopSettings
) -> tuple[float, Oscillation, str, SuspicionResult]:
    """Harris index, oscillation period, stiction verdict and suspicion of the longest stretch.

    A loop is judged only while it is "active" (valid PV and SP, not in MAN). This function
    picks the single longest continuously-active stretch and measures four things on it:

    * Harris index   -- a dimensionless measure of how close the loop is to its best
                        achievable performance (1.0 = no room for improvement, lower is worse).
    * oscillation period -- dominant cycle length in SECONDS, or ``None`` if no clear
                        oscillation is present.
    * stiction verdict   -- a string label for valve stiction (sticking of the control valve,
                        which can show up as a limit cycle).
    * stiction suspicion -- the ranked score of the cross-correlation method.

    Returns ``(harris, oscillation, stiction, suspicion)``; the suspicion is the ranked score of
    :func:`crosscut_loops.stiction_suspicion.stiction_suspicion`.
    """
    # `active` is a boolean mask over the samples; `_longest_run` returns a slice selecting
    # the longest unbroken run of True values, i.e. the longest active stretch.
    segment = _longest_run(active)
    stamps = series.t_s[segment]
    # A loop with no active stretch has an empty segment; its period still comes from the record.
    if len(stamps) < MIN_STAMPS_FOR_PERIOD:
        stamps = series.t_s
    dt_s = sampling_period(stamps, settings.scan_period_s)

    # The control error is process variable minus setpoint, computed sample-wise and then
    # restricted to the segment.
    harris, oscillation = _segment_metrics((series.pv - series.sp)[segment], dt_s, settings)

    # Stiction is detected from the relationship between the controller output (the valve
    # command, `out`) and the resulting process variable (`pv`), not from the error.
    stiction = _stiction_verdict(series.pv[segment], series.out[segment], dt_s, settings)

    suspicion = _suspicion(series, segment, dt_s, settings)

    return harris, oscillation, stiction, suspicion


def _valve_kpis(series: LoopSeries, active: np.ndarray, settings: LoopSettings) -> ValveKpis:
    """Valve wear and sizing numbers of the longest AUTO stretch (None when it is too short)."""
    segment = _longest_run(active)
    out = series.out[segment]
    out = out[~np.isnan(out)]
    if len(out) < MIN_KPI_SAMPLES or len(series.t_s[segment]) < MIN_STAMPS_FOR_PERIOD:
        return ValveKpis()
    ratio = quantisation_ratio(out)  # step / noise, scale-free: needs no OUT range
    quantisation = None if np.isnan(ratio) else float(ratio)
    if OUT_RANGE not in settings.known:
        return ValveKpis(quantisation=quantisation)
    dt_s = sampling_period(series.t_s[segment], settings.scan_period_s)
    span = settings.out_high - settings.out_low
    low, high = settings.out_low + 0.05 * span, settings.out_high - 0.05 * span
    return ValveKpis(
        travel=valve_travel_per_hour(out, dt_s, span),
        reversals=reversals_per_hour(out, dt_s, REVERSAL_MIN_MOVE_PERCENT / 100.0 * span),
        quantisation=quantisation,
        sizing=valve_extremes(out, low, high).sizing_hint,
    )


def _prepare_arrays(series: LoopSeries, settings: LoopSettings) -> LoopArrays:
    """Pick the active samples and compute the longest-stretch and valve metrics of a series.

    Returns a ``LoopArrays`` holding the raw signals, the boolean "active" mask, the tracking
    error restricted to the active samples, the sample count, and the Harris, oscillation,
    stiction and valve metrics.

    Raises ``ValueError`` (from ``sampling_period``) when the record has fewer than two
    timestamps.
    """
    # A sample is "active" (the loop is under automatic control) when PV and SP are valid,
    # quality is 0 where given, and the mode is not MAN. The mask is a boolean array of length
    # n_samples that every downstream metric relies on.
    active = _active_mask(series.pv, series.sp, series.mode, series.quality)

    # Harris index, oscillation and stiction metrics use the longest contiguous run of active
    # samples, because the methods assume a continuous AUTO stretch.
    harris, oscillation, stiction, suspicion = _longest_segment_metrics(series, active, settings)
    return LoopArrays(
        pv=series.pv,
        out=series.out,
        mode=series.mode,
        active=active,
        # Error is process variable minus setpoint, kept only where the loop is active; the
        # mask selects a variable-length subset, so its length is not n_samples.
        error=(series.pv - series.sp)[active],
        n_samples=len(series.t_s),
        harris=harris,
        oscillation=oscillation,
        stiction=stiction,
        suspicion=suspicion,
        valve=_valve_kpis(series, active, settings),
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
    # Bundle the raw channels into one value object so the pipeline below passes a single
    # argument around instead of parallel arrays (which are easy to mix up).
    series = LoopSeries(t_s=t_s, pv=pv, sp=sp, out=out, mode=mode, quality=quality)
    # Stage 1 - _prepare_arrays() computes the active mask and the longest-stretch metrics, and
    # _build_draft() turns them into the per-loop statistics: the "draft" report.
    draft = _build_draft(_prepare_arrays(series, settings), settings)
    # Stage 2 - the classification is derived from the draft statistics. `replace()` returns
    # a copy of the frozen dataclass with just that field swapped out.
    classified = replace(draft, classification=_classify(draft, settings))
    # Stage 3 - turn the classified numbers into human-readable finding sentences.
    return replace(classified, findings=_findings(classified, settings))
