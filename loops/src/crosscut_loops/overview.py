"""Overview of a plant-wide loop scan: loop discovery, findings, health score and dataset reports.

This module turns raw tag lists and recorded series into the JSON-ready summaries the web UI
shows: which loops exist, what is wrong with each of them, how healthy they are, and one compact
row per loop for the whole dataset.

The health score follows the documented assumption C5 in ``docs/ASSUMPTIONS.md``: a product of
shares, one per weakness, so it stays between 0 and 100 %. Missing values (NaN) are
reported as ``None`` so that the result survives ``json.dumps``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_loops.monitor import LoopReport, LoopSettings, analyze_loop

# --- Tag naming conventions -------------------------------------------------

# A loop is recognised by a PV tag whose sibling tags carry these suffixes.
SP_SUFFIX = "_sp"
OUT_SUFFIX = "_out"
MODE_SUFFIX = "_mode"
PV_ROLE = "PV"

# --- Default loop settings (used when the caller has no tuning knowledge) ---

DELAY_S = 30.0  # dead time assumed for an unknown loop, in seconds
ULTIMATE_PERIOD_S = 600.0  # natural oscillation period assumed, in seconds
AMPLITUDE_FRACTION = 0.02  # 2 % of the engineering range
FALLBACK_AMPLITUDE_LIMIT = 1.0  # amplitude limit when the engineering range is unknown
OUT_LOW = 0.0
OUT_HIGH = 100.0

# --- Health score penalties (assumption C5) ---------------------------------

HARRIS_FLOOR = 0.4  # share kept by a loop whose Harris index is 0
OSCILLATION_FACTOR = 0.7  # multiplier for a sustained oscillation
STICTION_FACTOR = 0.6  # multiplier when stiction is suspected
HARRIS_NEUTRAL = 0.5  # an uncomputable (NaN) Harris index counts as this fraction
HARRIS_FULL_SCORE = 1.0  # a Harris index at or above this keeps the full Harris share
POOR_HARRIS_THRESHOLD = 0.3  # below this the loop is "poor_performance" (mirrors LoopSettings)

# --- Finding codes and parameter names --------------------------------------

FLATLINE_CODE = "flatline"
MANUAL_CODE = "manual"
SATURATED_CODE = "saturated"
OSCILLATING_CODE = "oscillating"
POOR_PERFORMANCE_CODE = "poorPerformance"
STICTION_CODE = "stiction"

PERCENT_PARAM = "percent"
MINUTES_PARAM = "minutes"
SECONDS_PER_MINUTE = 60.0

# --- Finding severities -----------------------------------------------------

UNUSED_LEVEL = "unused"
PROBLEM_LEVEL = "problem"
WARNING_LEVEL = "warning"
OK_LEVEL = "ok"

MANUAL_CLASSIFICATION = "manual"
SATURATED_CLASSIFICATION = "saturated"
STICTION_VERDICT = "stiction"

# --- Dataset report layout --------------------------------------------------

SPARKLINE_POINTS = 48  # number of PV averages drawn in the row's mini chart


@dataclass(frozen=True)
class LoopTags:
    """One identified control loop and the tags that belong to it."""

    name: str
    pv: str
    sp: str
    out: str
    mode: str
    unit: str
    eng_min: float | None
    eng_max: float | None
    delay_s: float | None = None  # per-loop knowledge from the project file; None = use the default
    ultimate_period_s: float | None = None
    amplitude_limit: float | None = None


@dataclass(frozen=True)
class Finding:
    """One named problem of a loop, with the values needed to describe it."""

    code: str
    params: dict[str, Any]


def _role_of(row: Mapping[str, Any]) -> str | None:
    """Role string of one raw tag row, or None when the row carries no role."""
    role = row.get("role")
    return str(role) if role is not None else None


def _text_or_empty(value: Any) -> str:
    """The value as a string, or an empty string when it is missing."""
    return "" if value is None else str(value)


def _build_loop(tag_rows: Mapping[str, Mapping[str, Any]], pv_id: str) -> LoopTags:
    """Build the LoopTags of one loop from its PV id and the rows indexed by tag id.

    Raises:
        KeyError: if one of the sibling tags is missing (the caller checks first).
    """
    pv_row = tag_rows[pv_id]
    return LoopTags(
        name=pv_id.rsplit(".", 1)[-1],
        pv=pv_id,
        sp=pv_id + SP_SUFFIX,
        out=pv_id + OUT_SUFFIX,
        mode=pv_id + MODE_SUFFIX,
        unit=_text_or_empty(pv_row.get("unit")),
        eng_min=pv_row.get("eng_min"),
        eng_max=pv_row.get("eng_max"),
    )


def _has_sibling_tags(tag_rows: Mapping[str, Mapping[str, Any]], pv_id: str) -> bool:
    """True when SP, OUT and MODE tags exist for this PV tag."""
    return all(pv_id + suffix in tag_rows for suffix in (SP_SUFFIX, OUT_SUFFIX, MODE_SUFFIX))


def discover_loops(tags: Sequence[Mapping[str, Any]]) -> list[LoopTags]:
    """Find the complete loops among raw tag rows, in the order the PV tags appear.

    A loop counts when its PV tag has an ``_sp``, ``_out`` and ``_mode`` companion; a PV without
    them belongs to another naming convention and is skipped.

    A "loop" here is one closed control loop of the plant: the process variable (PV) that is
    measured, its setpoint (SP), its controller output (OUT) and its operating mode (MODE).
    Each piece arrives as its own tag row, so a loop is only usable when all four rows exist.

    Args:
        tags: raw tag rows with at least an ``id`` and a ``role`` key.

    Returns:
        The discovered loops, one per complete PV tag.
    """
    # Index the rows by tag id so the sibling lookups below are O(1) instead of a scan per tag.
    # Tag ids are stringified because the raw rows may carry them as ints or UUIDs, and the
    # lookups built further down compare against text ids.
    tag_rows = {str(row["id"]): row for row in tags}
    # Only PV rows can start a loop; their order comes from ``tag_rows``, i.e. the input order.
    pv_ids = [tag_id for tag_id, row in tag_rows.items() if _role_of(row) == PV_ROLE]
    # ``_has_sibling_tags`` is the completeness test described in the docstring: a PV whose
    # ``_sp``, ``_out`` or ``_mode`` companion is missing is left out rather than half-built.
    return [_build_loop(tag_rows, pv_id) for pv_id in pv_ids if _has_sibling_tags(tag_rows, pv_id)]


def _classify_finding(report: LoopReport) -> Finding | None:
    """The finding that names the report's classification, or None for a healthy loop.

    A control loop is monitored, then given exactly one label (its `classification`):
    healthy (no finding), manually controlled, saturated, oscillating, or poorly
    performing. Each label is translated into a Finding, which carries a code the
    UI can look up plus the numbers that code needs. This function is the single
    place where that translation happens, so the rest of the code only compares
    strings and stays free of UI details.

    Returns None when the loop is healthy, i.e. when no label matched.
    """
    if report.classification == MANUAL_CLASSIFICATION:
        # A loop left in manual mode is "as good" as its service factor: the
        # service_factor is the fraction of time, in [0.0, 1.0], during which
        # the loop was actually under automatic control. So 1.0 - service_factor
        # is the fraction of time it was NOT controlled, reported as a percentage.
        return Finding(MANUAL_CODE, {PERCENT_PARAM: _percent(1.0 - report.service_factor)})
    if report.classification == "saturated":
        # Saturation = the output sits at its limit (0 % or 100 % valve opening),
        # which means the controller asks for something the actuator cannot do.
        # saturation_fraction is the share of the records, in [0.0, 1.0], spent
        # there; the UI shows it as a percentage.
        return Finding(SATURATED_CODE, {PERCENT_PARAM: _percent(report.saturation_fraction)})
    if report.classification == OSCILLATING_CODE:
        # Oscillation = the loop cycles around its setpoint instead of settling.
        # The UI reads cycles better in minutes; the report stores seconds.
        minutes = (report.oscillation_period_s or 0.0) / SECONDS_PER_MINUTE
        # `or 0.0` above guards against a None period: a report classified as
        # oscillating may still have no measured period, in which case we fall
        # back to 0.0 minutes rather than crashing on a division by None.
        return Finding(OSCILLATING_CODE, {MINUTES_PARAM: minutes})
    if report.classification == "poor_performance":
        # Poor performance has no single number to display, so the Finding
        # carries an empty parameter mapping.
        return Finding(POOR_PERFORMANCE_CODE, {})
    return None


def findings_of(report: LoopReport, settings: LoopSettings) -> list[Finding]:
    """List the problems of one loop, most urgent first.

    A flatline comes first because it often explains every other finding; stiction comes last
    because fixing the valve is a maintenance action, not a retuning one.

    Each helper returns a Finding when it detects its problem, and None otherwise, so that the
    collectors stay independent: the order of the tuple below is the only place that decides
    the priority of the findings in the returned list.

    Args:
        report: the analysis of one loop.
        settings: the thresholds used for the analysis.

    Returns:
        Zero or more findings; an empty list means the loop looks healthy.
    """
    # Each helper is asked unconditionally, but a helper that sees nothing wrong returns None
    # (the "no finding" case); the tuple keeps the intended urgency order before filtering.
    candidates = (
        _flatline_finding(report, settings),  # controller output frozen: often the root cause
        _classify_finding(report),  # oscillation detected, but not necessarily a fault
        _stiction_finding(report),  # valve sticking: fixed by maintenance, not by tuning
    )
    # Drop the None entries ("no problem seen") and keep the tuple order, most urgent first.
    return [finding for finding in candidates if finding is not None]


def _flatline_finding(report: LoopReport, settings: LoopSettings) -> Finding | None:
    """The flatline finding, or None when the PV is not flat for too long."""
    if report.flatline_fraction <= settings.flatline_limit:
        return None
    return Finding(FLATLINE_CODE, {PERCENT_PARAM: _percent(report.flatline_fraction)})


def _percent(fraction: float) -> float:
    """A fraction as a whole percent, so the sentence shows "36 %" and not "36.1111 %"."""
    return float(round(fraction * 100.0))


def _stiction_suspected(report: LoopReport) -> bool:
    """Decide whether valve stiction is suspected for one control loop.

    Stiction counts only with a sustained oscillation and without saturation.

    A valve cycling between its stops makes a square PV cycle that looks like stiction, but the
    saturation finding already explains it. The oscillation detector must agree as a second opinion.

    Returns:
        True when the stiction verdict stands, an oscillation period was detected and the loop is
        not classified as saturated; False otherwise.
    """
    # All three conditions must hold at once, so the checks are chained with `and`:
    #   * the stiction detector raised its verdict (exact label match, not a substring test);
    #   * an oscillation period exists (in seconds, report.oscillation_period_s): a None period
    #     means no sustained cycle was found, so the square PV shape has another explanation;
    #   * the loop is not saturated: saturation already explains the cycling, which would
    #     otherwise be double-counted as stiction.
    return (
        report.stiction_verdict == STICTION_VERDICT
        and report.oscillation_period_s is not None
        and report.classification != SATURATED_CLASSIFICATION
    )


def _stiction_finding(report: LoopReport) -> Finding | None:
    """The stiction finding, or None when stiction is not suspected."""
    if not _stiction_suspected(report):
        return None
    return Finding(STICTION_CODE, {})


def _harris_share(harris_value: float) -> float:
    """Fraction (0..1) of the Harris weight a loop keeps for its Harris index.

    The Harris index measures how well a loop's references match the Harris matrix, which
    records the order in which statements are known to depend on each other; a higher value
    means the loop agrees with that ordering. This function is the scoring curve that maps the
    raw index to the share of the loop's weight the loop actually earns.

    A NaN index means the benchmark could not be computed: the loop is given the neutral half
    instead of being punished for missing data.

    Returns a value in [0.0, 1.0]; HARRIS_NEUTRAL for a missing measurement.
    """
    # Unit of harris_value: a correlation-like score in [-1, 1], where 1 means the loop's
    # references agree perfectly with the Harris matrix (so it scores 100%).
    if np.isnan(harris_value):
        return HARRIS_NEUTRAL
    if harris_value >= HARRIS_FULL_SCORE:
        return 1.0
    # A non-positive index earns nothing: the loop violates the known ordering and gets no credit.
    if harris_value <= 0.0:
        return 0.0
    # Linear ramp between 0 and HARRIS_FULL_SCORE: the score is used directly as the share.
    return float(harris_value)


def health_percent(report: LoopReport) -> int | None:
    """Health score of one loop, 0 to 100, or None when the loop is not in use.

    Product of independent shares (assumption C5 in ``docs/ASSUMPTIONS.md``): time in use, time not
    saturated, time not frozen, a Harris share between HARRIS_FLOOR and 1, and one factor each for a
    sustained oscillation and a suspected sticky valve. A product keeps the score
    in 0..100 and makes every weakness count.

    Args:
        report: the analysis of one loop.

    Returns:
        The rounded score, or None for a manual/unused loop that cannot be judged.
    """
    # A manual loop has no controller output to judge, so it has no score at all; None (rather than
    # 0) lets callers leave it out of averages instead of dragging them down.
    if report.classification == MANUAL_CLASSIFICATION:
        return None

    # All six sub-scores are decimal shares, each 0..1, so the product is a share as well.
    # _time_share groups the three "how much of the time could the loop act" terms; _harris_factor
    # groups the Harris index (controller performance) term; _behaviour_factor groups the penalty
    # terms for oscillation and a sticky valve. Multiplying means one bad aspect pulls the whole
    # score down, while a perfect loop lands on exactly 1.0.
    share = _time_share(report) * _harris_factor(report) * _behaviour_factor(report)

    # Clamp to 0..1 before scaling in case the sub-scores are slightly out of range, scale to a
    # 0..100 score and round to a whole point. int(round(...)) rather than round() alone so that a
    # whole-number float such as 72.0 comes back as 72, not as 72.0.
    return int(round(100.0 * min(1.0, max(0.0, share))))


def _time_share(report: LoopReport) -> float:
    """Fraction of time the loop is in use, not saturated and not frozen."""
    in_use = report.service_factor * (1.0 - report.saturation_fraction)
    return in_use * (1.0 - report.flatline_fraction)


def _harris_factor(report: LoopReport) -> float:
    """Multiplier between HARRIS_FLOOR and 1 from the Harris index."""
    return HARRIS_FLOOR + (1.0 - HARRIS_FLOOR) * _harris_share(report.harris_index)


def _behaviour_factor(report: LoopReport) -> float:
    """Multiplier below 1 for a sustained oscillation and for a suspected sticky valve.

    A control loop that oscillates or whose valve is sticking is less trustworthy, so the
    metrics derived from it are scaled down. The two penalties are independent and multiply,
    giving three possible outcomes: 1.0 (healthy), one factor alone, or both combined.

    Returns:
        The product of the applicable penalties, in the range [0, 1]. It is a dimensionless
        multiplier (no unit), applied later to a score rather than to a time or a percentage.
    """
    # Start from no penalty: 1.0 is the neutral value, so multiplying by it changes nothing
    # and a healthy loop leaves the downstream metric untouched.
    factor = 1.0
    # A sustained oscillation means the loop is not holding its setpoint. OSCILLATION_FACTOR
    # is a hard-coded constant below 1 (e.g. 0.5 means "half as trustworthy"); compounding it
    # with the sticky-valve penalty below punishes a loop that suffers from both at once.
    if report.classification == OSCILLATING_CODE:
        factor *= OSCILLATION_FACTOR
    # Stiction is a mechanical fault, not a control-tuning one, so it is detected separately
    # by inspecting the loop's behaviour rather than by its classification code.
    if _stiction_suspected(report):
        factor *= STICTION_FACTOR
    return factor


def _is_problem(report: LoopReport, settings: LoopSettings) -> bool:
    """True when the loop has a severe, maintenance-worthy problem."""
    return _stiction_suspected(report) or (report.flatline_fraction > settings.flatline_limit)


def status_level(report: LoopReport, settings: LoopSettings) -> str:
    """Traffic-light level of one loop: ``unused``, ``problem``, ``warning`` or ``ok``.

    The levels are checked in order of urgency, so a manual loop is always ``unused`` whatever
    else the report says.

    Args:
        report: the analysis of one loop.
        settings: the thresholds used for the analysis.

    Returns:
        One of UNUSED_LEVEL, PROBLEM_LEVEL, WARNING_LEVEL, OK_LEVEL.
    """
    # A "manual" loop is one a human wrote by hand instead of the optimizer generating it. There is
    # nothing to diagnose or tune in it, so it is reported as unused before any other rule applies.
    if report.classification == MANUAL_CLASSIFICATION:
        return UNUSED_LEVEL
    # _is_problem decides from measured quantities (see settings thresholds) whether the loop wastes
    # enough time or space to be worth fixing; it is the only check that can yield the top severity.
    if _is_problem(report, settings):
        return PROBLEM_LEVEL
    # Neither unused nor a clear problem, but still off: it runs in a degenerate regime (the trip
    # count is pinned at its maximum, the iteration count flips between values, or the measured
    # performance sits below the expected one for this loop shape).
    if report.classification in ("saturated", OSCILLATING_CODE, "poor_performance"):
        return WARNING_LEVEL
    # Nothing above fired: the loop is diagnosed as healthy and simply reported as such.
    return OK_LEVEL


def _amplitude_limit(eng_min: float | None, eng_max: float | None) -> float:
    """Acceptable oscillation amplitude for one engineering range, in PV units."""
    if eng_min is None or eng_max is None:
        return FALLBACK_AMPLITUDE_LIMIT
    return AMPLITUDE_FRACTION * (float(eng_max) - float(eng_min))


def default_settings(loop: LoopTags) -> LoopSettings:
    """Settings of a loop: the project-file values where given, otherwise placeholders.

    Args:
        loop: the loop to build settings for.

    Returns:
        Settings with the standard timing values and a 2 % amplitude limit, or 1.0 PV unit when
        the engineering range is unknown.
    """
    return LoopSettings(
        delay_s=_first_given(loop.delay_s, DELAY_S),
        ultimate_period_s=_first_given(loop.ultimate_period_s, ULTIMATE_PERIOD_S),
        amplitude_limit=_first_given(
            loop.amplitude_limit, _amplitude_limit(loop.eng_min, loop.eng_max)
        ),
        out_low=OUT_LOW,
        out_high=OUT_HIGH,
    )


def _first_given(value: float | None, fallback: float) -> float:
    """The per-loop value from the project file, or the fallback when it was not given."""
    return fallback if value is None else value


def _optional_float(value: float) -> float | None:
    """The value, or None when it is NaN (JSON has no NaN)."""
    return None if np.isnan(value) else float(value)


def _rounded_percent(fraction: float) -> int:
    """A 0..1 fraction as a rounded integer percentage."""
    return int(round(fraction * 100.0))


def _sparkline(pv: np.ndarray, points: int = SPARKLINE_POINTS) -> list[float]:
    """Down-sample the PV series to at most ``points`` chunk averages for the mini chart.

    ``pv`` is the photovoltaic power series, one sample per interval, in kW.
    Returns ``len(pv)`` values when the series is already short enough, otherwise exactly
    ``points`` values, each the mean power (kW) of an equal-sized block of consecutive samples.
    """
    # Short enough already: pass the samples through unchanged. The early return keeps the
    # chart honest for tiny windows, where averaging would hide a single peak.
    if len(pv) <= points:
        return [float(value) for value in pv]
    # Integer floor division: the chart should never gain synthetic samples, so any samples
    # left over at the tail (len(pv) % points of them) are simply dropped rather than padded.
    chunk_size = len(pv) // points
    # Cut the tail off, then fold the flat series into a (points, chunk_size) matrix whose row i
    # holds the samples of block i. reshape needs the length to be exactly chunk_size * points,
    # which is why the trim happens first.
    trimmed = pv[: chunk_size * points].reshape(points, chunk_size)
    # Mean over axis=1, i.e. within each block of consecutive samples, so every block becomes one
    # point on the chart.
    return [float(value) for value in trimmed.mean(axis=1)]


def _report_row(
    loop: LoopTags, report: LoopReport, settings: LoopSettings, pv_values: np.ndarray
) -> dict[str, Any]:
    """One JSON-ready row describing a loop, its report and its sparkline.

    A control loop is a feedback controller (usually PID) that drives a process
    variable (PV) towards a setpoint (SP). `report` holds the diagnostics computed
    for that loop, `settings` the thresholds those diagnostics are judged against.

    Returns a flat mapping whose keys become columns in the exported table.
    Numerical values are JSON-ready: no numpy scalars, no NaN, no infinities.
    """
    # The returned mapping is the row. `**_loop_identity(loop)` first spreads in the
    # identifying columns (tag, description, ...), then each diagnostic is added
    # under its own key. Keys after the spread win on collision.
    return {
        **_loop_identity(loop),
        # Ordinal severity of the loop, derived by comparing the report against the
        # configured thresholds. Not a number: a level such as "ok"/"warning"/"alert".
        "status": status_level(report, settings),
        # Overall health on a 0-100 scale, where 100 means no degradation detected.
        "health_percent": health_percent(report),
        # Label for the shape of the loop's behaviour, e.g. a well-tuned or an
        # oscillating loop. Free-form text produced by the classifier.
        "classification": report.classification,
        # One sub-row per problem detected in the loop, each already JSON-ready.
        "findings": _finding_rows(report, settings),
        # Fraction of time the controller output sits away from its limits, in
        # percent. Unit: percent, rounded for display.
        "service_percent": _rounded_percent(report.service_factor),
        # Fraction of time the controller output is pinned at a limit (0% or 100% of
        # its range): the valve is fully closed or fully open. Unit: percent.
        "saturation_percent": _rounded_percent(report.saturation_fraction),
        # Harris index: the ratio of the loop's achieved output variance to the
        # minimum variance a best-possible (minimum-variance) controller would
        # achieve on the same disturbance. Dimensionless; 1.0 means optimal, and
        # values well above 1 mean there is room for retuning.
        "harris_index": _optional_float(report.harris_index),
        # Dominant period of the oscillation seen in the PV, in seconds. Comes from
        # the spectral peak of the signal, hence the unit.
        "oscillation_period_s": _optional_period(report.oscillation_period_s),
        # Verdict on valve stiction: the stick-slip friction that makes a control
        # valve jump instead of moving smoothly. Free-form text, e.g. "sticking".
        "stiction_verdict": report.stiction_verdict,
        # Compact summary of the PV trend for inline display. Downsampled series of
        # (x, y) points, JSON-ready.
        "sparkline": _sparkline(pv_values),
    }


def _loop_identity(loop: LoopTags) -> dict[str, str]:
    """The identifying tags and unit of one loop, as they appear at the start of its CSV row.

    A "loop" is one control loop of a plant (a controller driving a measured variable to a
    setpoint). Its tags are the column names in the data file, so this mapping is the key
    that lets the rest of the module find a loop's signals in the export.

    Returns a dict with these keys, all values being raw column-name strings:
        name: loop identifier, e.g. "FIC-101"
        pv:   process variable, the measurement being controlled
        sp:   setpoint, the target value for the process variable
        out:  controller output, the signal sent to the final control element
        mode: controller mode (auto/manual) column name
        unit: engineering unit of the measurements, e.g. "%" or "m3/h", as text
    """
    return {
        "name": loop.name,
        "pv": loop.pv,
        "sp": loop.sp,
        "out": loop.out,
        "mode": loop.mode,
        "unit": loop.unit,
    }


def _finding_rows(report: LoopReport, settings: LoopSettings) -> list[dict[str, Any]]:
    """The findings of one loop as plain dictionaries for the JSON output."""
    return [
        {"code": finding.code, "params": finding.params}
        for finding in findings_of(report, settings)
    ]


def _optional_period(period_s: float | None) -> float | None:
    """The oscillation period, or None when no period was measured."""
    return None if period_s is None else _optional_float(period_s)


def analyze_dataset(
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    loops: Sequence[LoopTags],
) -> list[dict[str, Any]]:
    """Analyse every loop of one recording and return one JSON-ready row per loop.

    Paper name: "loop analysis" – the recording is cut into test loops and each loop is
    reduced to a small set of scalar metrics (yield, efficiency, ...) meant for export.

    Args:
        t_s: sample time stamps in seconds, shared by all columns.
        columns: the recorded series, indexed by the tag names used in ``loops``.
        loops: the loops to analyse, in the order the rows must be reported.

    Returns:
        One dictionary per loop, in input order; NaN values are replaced by None.

    Raises:
        KeyError: if a tag named by a loop is missing from ``columns``.

    Notes:
        This function is only a map: it owns no state and isolates no failure, so one
        bad loop raises and no rows are returned. The row order follows ``loops``, which
        is what downstream consumers (tables, charts) rely on to line up columns.
    """
    return [_analyse_one_loop(t_s, columns, loop) for loop in loops]


def _analyse_one_loop(
    t_s: np.ndarray, columns: Mapping[str, np.ndarray], loop: LoopTags
) -> dict[str, Any]:
    """Run the loop analysis on its own tags and return its JSON-ready row.

    A "loop" here is one control loop of a plant: a controlled variable (pv,
    measured process value), a setpoint (sp, the target pv should track), a
    controller output (out, the signal the controller sends to the valve) and
    a mode signal (mode, telling whether the loop is under automatic control
    or is held by the operator). This function wires those four signals of a
    single loop into the core analysis and packages the result for the report.

    Parameters:
        t_s: shared timestamps of every signal, in SECONDS from the start of
            the log. All columns are aligned with this array, index by index.
        columns: mapping from tag name to that tag's signal array, all of the
            same length as t_s.
        loop: the tag names identifying the four signals belonging to this loop.

    Returns:
        One report row (a plain dict) for this loop, ready to be serialised to
        JSON.
    """
    # Detection settings (thresholds, minimum hold durations, ...) can differ per
    # loop, so they are derived from this loop's tags rather than passed in.
    settings = default_settings(loop)
    report = analyze_loop(
        t_s,
        # Each argument is this loop's raw signal array, looked up by tag name.
        # The t_s and columns arrays are positional and share the same indexing,
        # so passing them together keeps every sample aligned in time.
        columns[loop.pv],
        columns[loop.sp],
        columns[loop.out],
        columns[loop.mode],
        settings=settings,
    )
    # Build the tabular report row from the analysis result. The pv array is
    # passed again so the row can carry summary statistics of the process
    # variable (min/max/mean, ...) alongside the detected events in `report`.
    return _report_row(loop, report, settings, columns[loop.pv])
