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

MIN_STAMPS_FOR_PERIOD = 2


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
    scan_period_s: float | None = None  # nominal logging period; overrides the estimate when set


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
) -> tuple[float, float | None]:
    """Harris index and oscillation period (None if none) of one uninterrupted AUTO stretch.

    The stretch is the error signal recorded while the controller stayed in AUTO without
    interruption; its quality is summarised by two numbers:

    * the Harris index from :func:`harris_index`, a unitless ratio that compares the
      achieved control performance with the best performance a minimum-variance
      controller could reach on the same signal (1.0 means "nothing left to improve");
    * the oscillation period in seconds from :func:`hagglund_oscillation`, or ``None``
      when the stretch does not oscillate persistently (Hagglund's method must fail).

    Returns a ``(harris, period_s)`` pair, with ``harris`` set to ``nan`` when the
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
        return float("nan"), None
    # The Harris index needs the dead time of the loop expressed as a whole number of
    # samples. Rounding the quotient delay_s / dt_s can give 0, but the algorithm needs
    # at least one sample of lag, hence the max(1, ...).
    delay_samples = max(1, round(settings.delay_s / dt_s))
    harris = harris_index(error, delay_samples)
    # Hagglund's method detects a sustained oscillation (limit cycle) and returns it
    # with its period; a stretch that does not oscillate yields period None.
    oscillation = hagglund_oscillation(
        error, dt_s, settings.amplitude_limit, settings.ultimate_period_s
    )
    return harris, oscillation.period_s


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

    # Harris index (dimensionless): the loop's variance divided by the variance of a minimum-
    # variance benchmark; lower is worse, 1.0 is optimal. Below harris_poor_threshold the loop is
    # stable but clearly underperforming.
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
    found = []
    # "Flatline" means the PV has stopped moving: the transmitter is probably stuck or the
    # data link is dead, and no statistic computed from a frozen signal is trustworthy.
    # flatline_fraction is a ratio in [0, 1]; comparing it to the limit is a plain fraction
    # comparison.
    if report.flatline_fraction > settings.flatline_limit:
        found.append(
            f"flatline: {report.flatline_fraction:.0%} of PV samples are frozen "
            "(stuck sensor or lost data)"
        )
    messages = {
        # service_factor is the fraction of samples that are active (valid PV/SP, quality 0 when
        # given, and not MAN). It is a ratio in [0, 1] and is rendered as a percentage.
        "manual": f"manual: in use only {report.service_factor:.0%} of the time",
        # saturation_fraction is the share of time the controller output sits at its low or
        # high limit, i.e. the manipulated variable cannot move any further.
        "saturated": f"saturated: output at its limit {report.saturation_fraction:.0%} of the time",
        # oscillation_period_s is the period of the detected cycle in seconds; the '_s' suffix
        # denotes seconds.
        "oscillating": f"oscillating: sustained cycle of {report.oscillation_period_s} s period",
        # harris_index is the ratio of the best achievable output variance to the variance the loop
        # actually delivers. A value near 1 means the controller is close to optimal; smaller values
        # mean poor control.
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
    """Assemble the unclassified report from the already-derived series metrics.

    The report collects per-series statistics of a control loop: the fraction of time the
    controller output is saturated, how often the setpoint changes, tracking error, the
    Harris index (a normalized performance measure, 1.0 means optimal minimum variance
    control), the estimated oscillation period in seconds, and the stiction verdict.
    Classification and findings stay empty here; a later stage fills them in.

    Returns a ``LoopReport`` with ``classification=""`` and ``findings=[]``.
    """
    # The saturation fraction is computed over ACTIVE samples only. arrays.active is a boolean mask;
    # inactive rows (startup/shutdown gaps) would otherwise bias the fraction. out_low/out_high are
    # the output limits in percent of output span, and the resulting saturation is a fraction in [0,
    # 1].
    saturation = saturation_fraction(arrays.out[arrays.active], settings.out_low, settings.out_high)
    return LoopReport(
        n_samples=arrays.n_samples,
        service_factor=float(np.mean(arrays.active)),
        saturation_fraction=saturation,
        # Share of time the process variable stops moving (|delta| below a deadband).
        flatline_fraction=flatline_fraction(arrays.pv),
        # Number of transitions in the discrete controller mode signal (auto/manual).
        mode_changes=_count_mode_changes(arrays.mode),
        # Mean of |error| with the axis of no data reduced to 0.0 instead of NaN.
        mean_abs_error=_mean_abs_or_zero(arrays.error),
        # Standard deviation of the error, same NaN-to-zero convention as above.
        error_std=_std_or_zero(arrays.error),
        # Harris index, dimensionless; 1.0 = best achievable (minimum variance) control.
        harris_index=arrays.harris,
        # Dominant oscillation period in seconds, or NaN if no oscillation was found.
        oscillation_period_s=arrays.period_s,
        # Left empty on purpose: the classifier that runs afterwards assigns the label.
        classification="",
        # Left empty on purpose: findings are appended by the later analysis stages.
        findings=[],
        stiction_verdict=arrays.stiction,
    )


def _longest_segment_metrics(
    series: LoopSeries, active: np.ndarray, settings: LoopSettings
) -> tuple[float, float | None, str]:
    """Harris index, oscillation period and stiction verdict of the longest active stretch.

    A control loop's behaviour is judged only while it is "active" (disturbed, not sitting
    at steady state).  This function picks the single longest continuously-active stretch
    and measures three things on it:

    * Harris index   -- a dimensionless measure of how close the loop is to its best
                        achievable performance (1.0 = no room for improvement, lower is worse).
    * oscillation period -- dominant cycle length in SECONDS, or ``None`` if no clear
                        oscillation is present.
    * stiction verdict   -- a string label describing valve stiction, the mechanical
                        sticking of the control valve that shows up as small limit cycles.

    Returns ``(harris, period_s, stiction)``.
    """

    # `active` is a boolean mask over the samples; `_longest_run` returns a slice selecting
    # the longest unbroken run of True values, i.e. the longest active stretch.
    segment = _longest_run(active)
    stamps = series.t_s[segment]
    # A loop with no active stretch has an empty segment; its period still comes from the record.
    if len(stamps) < MIN_STAMPS_FOR_PERIOD:
        stamps = series.t_s
    dt_s = sampling_period(stamps, settings.scan_period_s)

    # The control error is process variable minus setpoint: how far the measurement is from where we
    # asked it to be. Computed sample-wise, then restricted to the segment.
    harris, period_s = _segment_metrics((series.pv - series.sp)[segment], dt_s, settings)

    # Stiction is detected from the relationship between the controller output (the valve
    # command, `out`) and the resulting process variable (`pv`), not from the error.
    stiction = _stiction_verdict(series.pv[segment], series.out[segment], dt_s, settings)

    return harris, period_s, stiction


def _prepare_arrays(series: LoopSeries, settings: LoopSettings) -> LoopArrays:
    """Validate the series, pick the active samples and compute the stuck-out metrics.

    A control loop is a feedback system: a controller (here given by ``series.out``) moves the
    manipulated variable so that the process variable ``series.pv`` tracks the setpoint
    ``series.sp``. ``LoopArrays`` is the cleaned, pre-processed view of that loop on which the
    detection metrics below are computed.

    Returns a ``LoopArrays`` holding the raw signals, the boolean "active" mask, the tracking
    error restricted to the active samples, the sample count, and the Harris and stiction metrics.

    Raises ``ValueError`` (from ``_active_mask``) when the series is not valid for analysis.
    """
    # A sample is "active" (the loop is truly under closed-loop control) only when the
    # controller is in an automatic mode, the signals have good quality, and there is no
    # setpoint step. The mask is a boolean array of length n_samples that every downstream
    # metric relies on.
    active = _active_mask(series.pv, series.sp, series.mode, series.quality)

    # Compute the Harris index, dominant oscillation period, and stiction verdict on the
    # longest contiguous run of active samples. These three metrics rely on a continuous
    # AUTO stretch, so they are extracted before the per-sample statistics are assembled.
    harris, period_s, stiction = _longest_segment_metrics(series, active, settings)
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
    """Analyse one loop from its time stamps, PV, SP and OUT and MODE (0 = MAN) series.

    Only samples with a valid PV/SP (and quality 0 when given) outside MAN count as "active";
    Harris index and oscillation use the longest uninterrupted active stretch, because the
    methods assume a continuous series.
    """
    # Bundle the five raw channels into one value object so the pipeline below passes a single
    # argument around instead of five parallel arrays (which are easy to mix up).
    series = LoopSeries(t_s=t_s, pv=pv, sp=sp, out=out, mode=mode, quality=quality)
    # Stage 1 - _prepare_arrays() validates the signals, computes the active mask and the
    # longest-stretch metrics, and _build_draft() computes the raw per-loop statistics and
    # stores them in a frozen dataclass, the "draft" report.
    draft = _build_draft(_prepare_arrays(series, settings), settings)
    # Stage 2 - classification is derived from the draft statistics (e.g. which KPI band the
    # loop falls into). `replace()` returns a copy of the frozen dataclass with just that field
    # swapped out, keeping the earlier stages untouched.
    classified = replace(draft, classification=_classify(draft, settings))
    # Stage 3 - turn the classified numbers into human-readable findings (text + severity).
    # Each stage depends only on the previous one, so the pipeline reads top to bottom.
    return replace(classified, findings=_findings(classified, settings))
