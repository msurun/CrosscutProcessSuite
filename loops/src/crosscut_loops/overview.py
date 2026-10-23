"""Overview of a plant-wide loop scan: loop discovery, findings, health score and dataset reports.

This module turns raw tag lists and recorded series into the JSON-ready summaries the web UI
shows: which loops exist, what is wrong with each of them, how healthy they are, and one compact
row per loop for the whole dataset.

The health score follows the documented assumption C5 in ``docs/ASSUMPTIONS.md``: a product of
shares, one per weakness, so it stays between 0 and 100 %. Missing values (NaN) are
reported as ``None`` so that the result survives ``json.dumps``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from crosscut_loops.example_windows import example_window
from crosscut_loops.finding_windows import finding_window
from crosscut_loops.health_kpis import group_by_period
from crosscut_loops.monitor import (
    DELAY,
    OSCILLATION_LIMITS,
    OUT_RANGE,
    LoopReport,
    LoopSettings,
    analyze_loop,
)
from crosscut_loops.worklist import add_worklist

logger = logging.getLogger(__name__)

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

# --- Finding codes and parameter names --------------------------------------

FLATLINE_CODE = "flatline"
MANUAL_CODE = "manual"
SATURATED_CODE = "saturated"
OSCILLATING_CODE = "oscillating"
POOR_PERFORMANCE_CODE = "poorPerformance"
STICTION_CODE = "stiction"
NOISE_DRIVEN_CODE = "noise_driven"

WINDOW_KIND_CAUSE = "cause"
WINDOW_KIND_EXAMPLE = "example"

PERCENT_PARAM = "percent"
MINUTES_PARAM = "minutes"
SECONDS_PER_MINUTE = 60.0

# --- Finding severities -----------------------------------------------------

UNUSED_LEVEL = "unused"
PROBLEM_LEVEL = "problem"
WARNING_LEVEL = "warning"
OK_LEVEL = "ok"
# Nothing fired, but some checks were withheld for missing knowledge (see monitor.WITHHELD_BY).
NOT_ASSESSED_LEVEL = "not_assessed"

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
    out_low: float | None = None  # engineering minimum of the OUT tag; None = OUT_LOW
    out_high: float | None = None  # engineering maximum of the OUT tag; None = OUT_HIGH
    process_kind: str = "self_regulating"  # or "integrating" (level loop)


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
        # The OUT tag's own range is the actuator range used by the saturation checks.
        out_low=tag_rows[pv_id + OUT_SUFFIX].get("eng_min"),
        out_high=tag_rows[pv_id + OUT_SUFFIX].get("eng_max"),
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
    # Ids are stringified because the sibling ids are built by appending text suffixes.
    tag_rows = {str(row["id"]): row for row in tags}
    # Only PV rows can start a loop; their order comes from ``tag_rows``, i.e. the input order.
    pv_ids = [tag_id for tag_id, row in tag_rows.items() if _role_of(row) == PV_ROLE]
    return [_build_loop(tag_rows, pv_id) for pv_id in pv_ids if _has_sibling_tags(tag_rows, pv_id)]


def _classify_finding(report: LoopReport) -> Finding | None:
    """The finding that names the report's classification, or None for a healthy loop.

    The classification is one label per loop (manual, saturated, oscillating, poor performance
    or healthy). Each label becomes a Finding: a code the UI looks up plus the numbers that code
    needs. Percentages are whole numbers, the oscillation period is in minutes.
    """
    if report.classification == MANUAL_CLASSIFICATION:
        # Share of the time the loop was not in service (the complement of service_factor).
        return Finding(MANUAL_CODE, {PERCENT_PARAM: _percent(1.0 - report.service_factor)})
    if report.classification == "saturated":
        # Share of the active samples with OUT at one of its limits.
        return Finding(SATURATED_CODE, {PERCENT_PARAM: _percent(report.saturation_fraction)})
    if report.classification == OSCILLATING_CODE:
        # The report stores seconds, the UI reads cycles better in minutes. A report classified
        # as oscillating may still lack a period; 0.0 then avoids a division by None.
        minutes = (report.oscillation_period_s or 0.0) / SECONDS_PER_MINUTE
        return Finding(OSCILLATING_CODE, {MINUTES_PARAM: minutes})
    if report.classification == "poor_performance":
        # No single number to display, so the parameters stay empty.
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
    # Every helper is asked; one that sees nothing wrong returns None. The tuple order is the
    # urgency order.
    candidates = (
        _flatline_finding(report, settings),  # PV frozen: often the root cause
        _classify_finding(report),  # manual, saturated, oscillating or poor performance
        _stiction_finding(report),  # valve sticking: fixed by maintenance, not by tuning
        _noise_driven_finding(report),  # control action driven by measurement noise
    )
    # Drop the None entries and keep the tuple order, most urgent first.
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


# Exploratory thresholds of the noise-driven check (2026-10-23, first real flotation data): a valve
# that travels this much and reverses this often while no regular cycle exists is moved by
# measurement noise, not by a disturbance. On the owner's 10 s records level loops showed 55-350 %/h
# and 37-190 reversals/h, flow loops 1-37 %/h; the values are advice limits, not validated.
NOISE_TRAVEL_PER_H = 50.0
NOISE_REVERSALS_PER_H = 30.0
TRAVEL_PARAM = "travel"
REVERSALS_PARAM = "reversals"


def is_noise_driven(report: LoopReport) -> bool:
    """True when the valve moves a lot and reverses often but the loop shows no regular cycle.

    Needs the valve KPIs (OUT range known). A manual loop and an oscillating loop have their own
    findings, so they are excluded here.
    """
    travel, reversals = report.valve_travel_per_h, report.valve_reversals_per_h
    if travel is None or reversals is None:
        return False
    if report.classification in (MANUAL_CLASSIFICATION, OSCILLATING_CODE):
        return False
    return travel >= NOISE_TRAVEL_PER_H and reversals >= NOISE_REVERSALS_PER_H


def _noise_driven_finding(report: LoopReport) -> Finding | None:
    """The noise-driven finding with the valve travel and reversal rates, or None."""
    if not is_noise_driven(report):
        return None
    travel, reversals = report.valve_travel_per_h or 0.0, report.valve_reversals_per_h or 0.0
    params = {TRAVEL_PARAM: round(travel), REVERSALS_PARAM: round(reversals)}
    return Finding(NOISE_DRIVEN_CODE, params)


def _harris_share(harris_value: float) -> float:
    """Fraction (0..1) of the Harris weight a loop keeps for its Harris index.

    The Harris index is the minimum-variance benchmark variance divided by the loop's achieved
    error variance (Harris 1989): 1.0 means no controller could do better with this dead time,
    values near 0 mean most of the variance could be removed by better control. This function is
    the scoring curve that maps the index to the share of the Harris weight the loop keeps.

    A NaN index means the benchmark could not be computed: the loop is given the neutral half
    instead of being punished for missing data.

    Returns a value in [0.0, 1.0]; HARRIS_NEUTRAL for a missing measurement.
    """
    # harris_value is a variance ratio, nominally in [0, 1]; estimation noise can push it a
    # little outside, hence the clamps below.
    if np.isnan(harris_value):
        return HARRIS_NEUTRAL
    if harris_value >= HARRIS_FULL_SCORE:
        return 1.0
    # A non-positive index (only possible from estimation noise) earns nothing.
    if harris_value <= 0.0:
        return 0.0
    # In between, the index itself is the share (HARRIS_FULL_SCORE is 1.0, so the ramp from 0
    # to full score has slope 1).
    return float(harris_value)


def health_percent(report: LoopReport) -> int | None:
    """Health score of one loop, 0 to 100, or None when it is not in use or cannot be scored.

    Product of independent shares (assumption C5 in ``docs/ASSUMPTIONS.md``): time in use, time not
    saturated, time not frozen, a Harris share between HARRIS_FLOOR and 1, and one factor each for a
    sustained oscillation and a suspected sticky valve. A product keeps the score
    in 0..100 and makes every weakness count.

    Args:
        report: the analysis of one loop.

    Returns:
        The rounded score, or None for a manual/unused loop or a loop without a Harris index.
    """
    # A service factor above 1.0 is impossible for a fraction of time, so it points at bad input.
    # The score is still computed unchanged; the warning only asks the operator to check the data.
    if report.service_factor > 1.0:
        logger.warning(
            "service_factor %.3f is above 1.0; health score may be inflated",
            report.service_factor,
        )
    # A manual loop has no controller output to judge, so it has no score at all; None (rather than
    # 0) lets callers leave it out of averages instead of dragging them down.
    if report.classification == MANUAL_CLASSIFICATION:
        return None
    # Without a Harris index the score would rest on an imputed value (HARRIS_NEUTRAL), which looks
    # like a measurement. The loop is not scored; `not_assessed` tells the user what is missing.
    if np.isnan(report.harris_index):
        return None

    # All six sub-scores are decimal shares, each 0..1, so the product is a share as well.
    # _time_share groups the three "how much of the time could the loop act" terms; _harris_factor
    # groups the Harris index (controller performance) term; _behaviour_factor groups the penalty
    # terms for oscillation and a sticky valve. Multiplying means one bad aspect pulls the whole
    # score down, while a perfect loop lands on exactly 1.0.
    share = _time_share(report) * _harris_factor(report) * _behaviour_factor(report)

    # Clamp to 0..1 in case a sub-score is slightly out of range, scale to 0..100 and round to
    # a whole point.
    return int(round(100.0 * min(1.0, max(0.0, share))))


def _time_share(report: LoopReport) -> float:
    """Fraction of time the loop is in use, not saturated and not frozen.

    An unknown saturation (NaN: the OUT range is not configured) is not penalised.
    """
    saturation = 0.0 if np.isnan(report.saturation_fraction) else report.saturation_fraction
    in_use = report.service_factor * (1.0 - saturation)
    return in_use * (1.0 - report.flatline_fraction)


def _harris_factor(report: LoopReport) -> float:
    """Multiplier between HARRIS_FLOOR and 1 from the Harris index."""
    return HARRIS_FLOOR + (1.0 - HARRIS_FLOOR) * _harris_share(report.harris_index)


def _behaviour_factor(report: LoopReport) -> float:
    """Multiplier below 1 for a sustained oscillation and for a suspected sticky valve.

    A loop that oscillates or whose valve is suspected to stick is less healthy, so its score
    is scaled down. The two penalties are independent and multiply, giving four outcomes: 1.0,
    the oscillation factor alone, the stiction factor alone, or both combined.

    Returns:
        The product of the applicable penalties, a dimensionless multiplier in (0, 1].
    """
    # Start from no penalty: 1.0 is the neutral value, so multiplying by it changes nothing
    # and a healthy loop leaves the downstream metric untouched.
    factor = 1.0
    # A sustained oscillation means the loop is not holding its setpoint: the score is
    # multiplied by OSCILLATION_FACTOR (a named constant below 1, assumption C5).
    if report.classification == OSCILLATING_CODE:
        factor *= OSCILLATION_FACTOR
    # Stiction is a valve fault, not a tuning one; it comes from the stiction verdict, not from
    # the classification, so it can apply on top of an oscillating loop.
    if _stiction_suspected(report):
        factor *= STICTION_FACTOR
    return factor


def _is_problem(report: LoopReport, settings: LoopSettings) -> bool:
    """True when the loop has a severe, maintenance-worthy problem."""
    return _stiction_suspected(report) or (report.flatline_fraction > settings.flatline_limit)


def status_level(report: LoopReport, settings: LoopSettings) -> str:
    """Traffic-light level: ``unused``, ``problem``, ``warning``, ``not_assessed`` or ``ok``.

    The levels are checked in order of urgency, so a manual loop is always ``unused`` whatever
    else the report says.

    Args:
        report: the analysis of one loop.
        settings: the thresholds used for the analysis.

    Returns:
        One of UNUSED_LEVEL, PROBLEM_LEVEL, WARNING_LEVEL, NOT_ASSESSED_LEVEL, OK_LEVEL.
    """
    # A "manual" loop spends most of the time out of AUTO (service factor below manual_limit):
    # the operator runs it by hand, so there is no controller behaviour to judge yet.
    if report.classification == MANUAL_CLASSIFICATION:
        return UNUSED_LEVEL
    # A suspected sticking valve or a frozen PV needs maintenance, not retuning: top severity.
    if _is_problem(report, settings):
        return PROBLEM_LEVEL
    # Off but not broken: OUT pinned at a limit, a sustained oscillation, or a Harris index below
    # the threshold. Each of these is only reached when its knowledge is configured (see
    # monitor.WITHHELD_BY); otherwise the report lists it under not_assessed.
    if report.classification in ("saturated", OSCILLATING_CODE, "poor_performance"):
        return WARNING_LEVEL
    # A valve moved by noise wears out and adds noise to the process although no cycle shows.
    if is_noise_driven(report):
        return WARNING_LEVEL
    # Nothing fired, but if checks were withheld for missing per-loop knowledge, "no problem" would
    # only mean "no problem in the checks that ran": say so instead of showing a green OK.
    if report.not_assessed:
        return NOT_ASSESSED_LEVEL
    # Nothing above fired and every check ran: the loop is diagnosed as healthy.
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

    Placeholders keep the numbers defined, but ``known`` lists only what the project file gave,
    so the analysis withholds the conclusions that would rest on a placeholder.

    Returns:
        Settings with the standard timing values and a 2 % amplitude limit, or 1.0 PV unit when
        the engineering range is unknown.
    """
    return LoopSettings(
        known=_known_from_tags(loop),
        delay_s=_first_given(loop.delay_s, DELAY_S),
        ultimate_period_s=_first_given(loop.ultimate_period_s, ULTIMATE_PERIOD_S),
        amplitude_limit=_first_given(
            loop.amplitude_limit, _amplitude_limit(loop.eng_min, loop.eng_max)
        ),
        out_low=_first_given(loop.out_low, OUT_LOW),
        out_high=_first_given(loop.out_high, OUT_HIGH),
        process_kind=loop.process_kind,
    )


def _known_from_tags(loop: LoopTags) -> frozenset[str]:
    """The per-loop knowledge the project file actually provides.

    The oscillation limits need the ultimate period plus an amplitude limit, either given
    directly or derived from a configured PV engineering range (AMPLITUDE_FRACTION of it).
    """
    has_range = loop.eng_min is not None and loop.eng_max is not None
    given = {
        OUT_RANGE: loop.out_low is not None and loop.out_high is not None,
        DELAY: loop.delay_s is not None,
        OSCILLATION_LIMITS: loop.ultimate_period_s is not None
        and (loop.amplitude_limit is not None or has_range),
    }
    return frozenset(name for name, ok in given.items() if ok)


def _first_given(value: float | None, fallback: float) -> float:
    """The per-loop value from the project file, or the fallback when it was not given."""
    return fallback if value is None else value


def _optional_float(value: float) -> float | None:
    """The value, or None when it is NaN (JSON has no NaN)."""
    return None if np.isnan(value) else float(value)


def _rounded_percent(fraction: float) -> int:
    """A 0..1 fraction as a rounded integer percentage."""
    return int(round(fraction * 100.0))


def _optional_percent(fraction: float) -> int | None:
    """A 0..1 fraction as a rounded percentage, or None when it is NaN (not assessed)."""
    return None if np.isnan(fraction) else _rounded_percent(fraction)


def _sparkline(pv: np.ndarray, points: int = SPARKLINE_POINTS) -> list[float]:
    """Down-sample the PV series to at most ``points`` chunk averages for the mini chart.

    ``pv`` is the process value series, one sample per interval.
    Returns ``len(pv)`` values when the series is already short enough, otherwise exactly
    ``points`` values, each the mean of a block of consecutive samples. Every sample belongs
    to a block: the blocks differ in size by at most one sample, so no tail is dropped.
    """
    # If the series is already short enough, return it unchanged; averaging would hide peaks.
    if len(pv) <= points:
        return [float(value) for value in pv]
    # array_split gives the first len(pv) % points blocks one extra sample, so the tail
    # samples land in the last block instead of being silently discarded.
    blocks = np.array_split(pv, points)
    return [float(np.mean(block)) for block in blocks]


def _report_row(
    loop: LoopTags, report: LoopReport, settings: LoopSettings, pv_values: np.ndarray
) -> dict[str, Any]:
    """One JSON-ready row describing a loop, its report and its sparkline.

    `report` holds the diagnostics computed for that loop, `settings` the thresholds those
    diagnostics are judged against.

    Returns a flat mapping whose keys become columns in the exported table.
    Numerical values are JSON-ready: no numpy scalars, no NaN, no infinities.
    """
    # Identifying columns first, then diagnostics, then the withheld conclusions and sparkline.
    return {
        **_loop_identity(loop),
        **_health_columns(report, settings),
        **_valve_columns(report),
        # Conclusions withheld because their per-loop knowledge is not configured.
        "not_assessed": list(report.not_assessed),
        # Downsampled PV values for the inline sparkline chart.
        "sparkline": _sparkline(pv_values),
    }


def _health_columns(report: LoopReport, settings: LoopSettings) -> dict[str, Any]:
    """Status, health, classification, findings and oscillation columns of one row."""
    return {
        # Severity level of the loop: one of "unused", "problem", "warning", "ok".
        "status": status_level(report, settings),
        # Overall health percentage (0-100); 100 means no degradation detected.
        "health_percent": health_percent(report),
        # Classification label of the loop's behavior, e.g. "manual", "saturated", "oscillating".
        "classification": report.classification,
        # List of findings, each a dict with "code" and "params".
        "findings": _finding_rows(report, settings),
        # Percentage of time the controller is in automatic mode (service factor), rounded.
        "service_percent": _rounded_percent(report.service_factor),
        # Percentage of time OUT sits at a limit, rounded; None when the OUT range is unknown.
        "saturation_percent": _optional_percent(report.saturation_fraction),
        # Harris index: minimum-variance benchmark over achieved variance; 1.0 is best, lower worse.
        "harris_index": _optional_float(report.harris_index),
        # Dominant oscillation period in seconds; None if no oscillation was detected.
        "oscillation_period_s": _optional_period(report.oscillation_period_s),
        # "hagglund" (configured limits), "acf" (parameter-free regularity) or None.
        "oscillation_method": report.oscillation_method,
    }


def _valve_columns(report: LoopReport) -> dict[str, Any]:
    """Stiction verdict, valve travel and sizing columns of one row."""
    return {
        # Stiction verdict label of the monitor; "not_checked" when no stretch could be judged.
        "stiction_verdict": report.stiction_verdict,
        # Ranked stiction suspicion (0..1 or None) and the advice derived from it.
        "stiction_suspicion": report.stiction_suspicion,
        "stiction_advice": report.stiction_advice,
        "valve_travel_per_h": report.valve_travel_per_h,
        "valve_reversals_per_h": report.valve_reversals_per_h,
        "out_quantisation_ratio": report.out_quantisation_ratio,
        "valve_sizing_hint": report.valve_sizing_hint,
    }


def _loop_identity(loop: LoopTags) -> dict[str, str]:
    """The identifying tags and unit of one loop, as they appear at the start of its CSV row.

    The tags are the column names in the data file, so this mapping lets the rest of the
    module find a loop's signals.

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

    Each row holds the loop tags, status, health score, findings (with a trend window where one
    exists), the monitor KPIs, a sparkline, the loops that cycle at the same period and the
    next action of the worklist.

    Args:
        t_s: sample time stamps in seconds, shared by all columns.
        columns: the recorded series, indexed by the tag names used in ``loops``.
        loops: the loops to analyse, in the order the rows must be reported.

    Returns:
        One dictionary per loop, in input order; NaN values are replaced by None.

    Raises:
        KeyError: if a tag named by a loop is missing from ``columns``.

    Notes:
        One bad loop raises and no rows are returned: failures are not isolated per loop.
    """
    rows = [_analyse_one_loop(t_s, columns, loop) for loop in loops]
    _add_shared_periods(rows)
    # Needs same_period_as, so it runs last: next_action and priority_rank per row.
    add_worklist(rows)
    return rows


def _add_shared_periods(rows: list[dict[str, Any]]) -> None:
    """Give each row "same_period_as": the other loops cycling at about the same period.

    "About the same" is `group_by_period`'s default: within 10 % above the shortest period of
    the cluster.

    Loops that oscillate together often share one disturbance source, so the list points at
    where to look first; it is a hint, not a proof of a common cause.
    """
    periods = {
        row["name"]: row["oscillation_period_s"]
        for row in rows
        if row["oscillation_period_s"] is not None
    }
    peers = {name: cluster for cluster in group_by_period(periods) for name in cluster}
    for row in rows:
        row["same_period_as"] = [peer for peer in peers.get(row["name"], []) if peer != row["name"]]


def _analyse_one_loop(
    t_s: np.ndarray, columns: Mapping[str, np.ndarray], loop: LoopTags
) -> dict[str, Any]:
    """Run the loop analysis on the PV, SP, OUT and MODE tags of one loop; return its row.

    Parameters:
        t_s: shared timestamps of every signal, in seconds; all columns are aligned with it.
        columns: mapping from tag name to that tag's signal array (same length as t_s).
        loop: the tag names identifying the four signals belonging to this loop.

    Returns:
        One report row (a plain dict) for this loop, ready to be serialised to JSON.
    """
    # Settings may vary per loop, so they are derived from the loop's configuration.
    settings = default_settings(loop)
    report = analyze_loop(
        t_s,
        # Raw signal arrays are aligned with t_s by index; look up each by tag name.
        columns[loop.pv],
        columns[loop.sp],
        columns[loop.out],
        columns[loop.mode],
        settings=settings,
    )
    # Include the PV array again for the row's sparkline summary.
    row = _report_row(loop, report, settings, columns[loop.pv])
    _add_finding_windows(row, t_s, columns, loop)
    return row


def _add_finding_windows(
    row: dict[str, Any],
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    loop: LoopTags,
) -> None:
    """Attach ``window_s`` = [start_s, end_s] and ``window_kind`` to findings of one row.

    The window lets the UI zoom the trend. ``window_kind`` is "cause" when the stretch is what
    produced the finding (manual, saturated, flatline) and "example" for findings about the whole
    record (oscillation, poor performance, stiction), where it is the stretch with the largest
    control error, so the UI can word the link honestly.
    """
    for finding in row["findings"]:
        window = _cause_window(finding["code"], t_s, columns, loop)
        kind = WINDOW_KIND_CAUSE
        if window is None:
            period_s = row["oscillation_period_s"]
            window = example_window(
                finding["code"], t_s, columns[loop.pv], columns[loop.sp], period_s
            )
            kind = WINDOW_KIND_EXAMPLE
        if window is not None:
            finding["window_s"] = [window[0], window[1]]
            finding["window_kind"] = kind


def _cause_window(
    code: str, t_s: np.ndarray, columns: Mapping[str, np.ndarray], loop: LoopTags
) -> tuple[float, float] | None:
    """The stretch of data that caused a finding, or None when it has no single cause stretch."""
    return finding_window(
        code,
        t_s,
        columns[loop.pv],
        columns[loop.out],
        columns[loop.mode],
        out_low=_first_given(loop.out_low, OUT_LOW),
        out_high=_first_given(loop.out_high, OUT_HIGH),
    )
