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

    Args:
        tags: raw tag rows with at least an ``id`` and a ``role`` key.

    Returns:
        The discovered loops, one per complete PV tag.
    """
    tag_rows = {str(row["id"]): row for row in tags}
    pv_ids = [tag_id for tag_id, row in tag_rows.items() if _role_of(row) == PV_ROLE]
    return [_build_loop(tag_rows, pv_id) for pv_id in pv_ids if _has_sibling_tags(tag_rows, pv_id)]


def _classify_finding(report: LoopReport) -> Finding | None:
    """The finding that names the report's classification, or None for a healthy loop."""
    if report.classification == MANUAL_CLASSIFICATION:
        return Finding(MANUAL_CODE, {PERCENT_PARAM: _percent(1.0 - report.service_factor)})
    if report.classification == "saturated":
        return Finding(SATURATED_CODE, {PERCENT_PARAM: _percent(report.saturation_fraction)})
    if report.classification == OSCILLATING_CODE:
        # The UI reads cycles better in minutes; the report stores seconds.
        minutes = (report.oscillation_period_s or 0.0) / SECONDS_PER_MINUTE
        return Finding(OSCILLATING_CODE, {MINUTES_PARAM: minutes})
    if report.classification == "poor_performance":
        return Finding(POOR_PERFORMANCE_CODE, {})
    return None


def findings_of(report: LoopReport, settings: LoopSettings) -> list[Finding]:
    """List the problems of one loop, most urgent first.

    A flatline comes first because it often explains every other finding; stiction comes last
    because fixing the valve is a maintenance action, not a retuning one.

    Args:
        report: the analysis of one loop.
        settings: the thresholds used for the analysis.

    Returns:
        Zero or more findings; an empty list means the loop looks healthy.
    """
    candidates = (
        _flatline_finding(report, settings),
        _classify_finding(report),
        _stiction_finding(report),
    )
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
    """Stiction counts only together with a sustained oscillation (a limit cycle).

    The THD test alone also fires on noise-driven variation (seen on every loop of the simulated
    mill circuit), so the overview requires the oscillation detector to agree before an alarm.
    """
    return report.stiction_verdict == STICTION_VERDICT and report.oscillation_period_s is not None


def _stiction_finding(report: LoopReport) -> Finding | None:
    """The stiction finding, or None when stiction is not suspected."""
    if not _stiction_suspected(report):
        return None
    return Finding(STICTION_CODE, {})


def _harris_share(harris_value: float) -> float:
    """Fraction (0..1) of the Harris weight a loop keeps for its Harris index.

    A NaN index means the benchmark could not be computed: the loop is given the neutral half
    instead of being punished for missing data.
    """
    if np.isnan(harris_value):
        return HARRIS_NEUTRAL
    if harris_value >= HARRIS_FULL_SCORE:
        return 1.0
    if harris_value <= 0.0:
        return 0.0
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
    if report.classification == MANUAL_CLASSIFICATION:
        return None
    share = _time_share(report) * _harris_factor(report) * _behaviour_factor(report)
    return int(round(100.0 * min(1.0, max(0.0, share))))


def _time_share(report: LoopReport) -> float:
    """Fraction of time the loop is in use, not saturated and not frozen."""
    in_use = report.service_factor * (1.0 - report.saturation_fraction)
    return in_use * (1.0 - report.flatline_fraction)


def _harris_factor(report: LoopReport) -> float:
    """Multiplier between HARRIS_FLOOR and 1 from the Harris index."""
    return HARRIS_FLOOR + (1.0 - HARRIS_FLOOR) * _harris_share(report.harris_index)


def _behaviour_factor(report: LoopReport) -> float:
    """Multiplier below 1 for a sustained oscillation and for a suspected sticky valve."""
    factor = 1.0
    if report.classification == OSCILLATING_CODE:
        factor *= OSCILLATION_FACTOR
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
    if report.classification == MANUAL_CLASSIFICATION:
        return UNUSED_LEVEL
    if _is_problem(report, settings):
        return PROBLEM_LEVEL
    if report.classification in ("saturated", OSCILLATING_CODE, "poor_performance"):
        return WARNING_LEVEL
    return OK_LEVEL


def _amplitude_limit(eng_min: float | None, eng_max: float | None) -> float:
    """Acceptable oscillation amplitude for one engineering range, in PV units."""
    if eng_min is None or eng_max is None:
        return FALLBACK_AMPLITUDE_LIMIT
    return AMPLITUDE_FRACTION * (float(eng_max) - float(eng_min))


def default_settings(loop: LoopTags) -> LoopSettings:
    """Starting settings for a loop we know nothing about beyond its tags.

    Args:
        loop: the loop to build settings for.

    Returns:
        Settings with the standard timing values and a 2 % amplitude limit, or 1.0 PV unit when
        the engineering range is unknown.
    """
    return LoopSettings(
        delay_s=DELAY_S,
        ultimate_period_s=ULTIMATE_PERIOD_S,
        amplitude_limit=_amplitude_limit(loop.eng_min, loop.eng_max),
        out_low=OUT_LOW,
        out_high=OUT_HIGH,
    )


def _optional_float(value: float) -> float | None:
    """The value, or None when it is NaN (JSON has no NaN)."""
    return None if np.isnan(value) else float(value)


def _rounded_percent(fraction: float) -> int:
    """A 0..1 fraction as a rounded integer percentage."""
    return int(round(fraction * 100.0))


def _sparkline(pv: np.ndarray, points: int = SPARKLINE_POINTS) -> list[float]:
    """Down-sample the PV series to at most ``points`` chunk averages for the mini chart."""
    if len(pv) <= points:
        return [float(value) for value in pv]
    chunk_size = len(pv) // points
    trimmed = pv[: chunk_size * points].reshape(points, chunk_size)
    return [float(value) for value in trimmed.mean(axis=1)]


def _report_row(
    loop: LoopTags, report: LoopReport, settings: LoopSettings, pv_values: np.ndarray
) -> dict[str, Any]:
    """One JSON-ready row describing a loop, its report and its sparkline."""
    return {
        **_loop_identity(loop),
        "status": status_level(report, settings),
        "health_percent": health_percent(report),
        "classification": report.classification,
        "findings": _finding_rows(report, settings),
        "service_percent": _rounded_percent(report.service_factor),
        "saturation_percent": _rounded_percent(report.saturation_fraction),
        "harris_index": _optional_float(report.harris_index),
        "oscillation_period_s": _optional_period(report.oscillation_period_s),
        "stiction_verdict": report.stiction_verdict,
        "sparkline": _sparkline(pv_values),
    }


def _loop_identity(loop: LoopTags) -> dict[str, str]:
    """The tag names and unit of one loop, as they appear at the start of its row."""
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

    Args:
        t_s: sample time stamps in seconds, shared by all columns.
        columns: the recorded series, indexed by the tag names used in ``loops``.
        loops: the loops to analyse, in the order the rows must be reported.

    Returns:
        One dictionary per loop, in input order; NaN values are replaced by None.

    Raises:
        KeyError: if a tag named by a loop is missing from ``columns``.
    """
    return [_analyse_one_loop(t_s, columns, loop) for loop in loops]


def _analyse_one_loop(
    t_s: np.ndarray, columns: Mapping[str, np.ndarray], loop: LoopTags
) -> dict[str, Any]:
    """Run the loop analysis on its own tags and return its JSON-ready row."""
    settings = default_settings(loop)
    report = analyze_loop(
        t_s,
        columns[loop.pv],
        columns[loop.sp],
        columns[loop.out],
        columns[loop.mode],
        settings=settings,
    )
    return _report_row(loop, report, settings, columns[loop.pv])
