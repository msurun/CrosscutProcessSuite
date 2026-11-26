"""Turn an overview's per-loop rows into a prioritised worklist: one next action per loop.

The ordering here is a rule of thumb for advice, not a validated score: saying which fix comes
first would need a blind review by a control engineer on real plant data. Until then, this module
only says what to look at next, and in which order.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from crosscut_loops.health_kpis import QUANTISATION_LIMITING

# --- Action codes shown to the operator -------------------------------------

ASK_WHY_MANUAL = "ask_why_manual"
CHECK_MEASUREMENT = "check_measurement"
CHECK_OUTPUT_LIMIT = "check_output_limit"
VALVE_TEST = "valve_test"
FIND_COMMON_SOURCE = "find_common_source"
TEST_CYCLE_CAUSE = "test_cycle_cause"
CHECK_OUTPUT_RESOLUTION = "check_output_resolution"
BUMP_TEST_AND_RETUNE = "bump_test_and_retune"
REVIEW_NOISE_RESPONSE = "review_noise_response"
REVIEW_VALVE_SIZING = "review_valve_sizing"
CONFIGURE_KNOWLEDGE = "configure_knowledge"
NO_ACTION = "none"

# --- Row values this module reads -------------------------------------------

MANUAL_CLASSIFICATION = "manual"
SATURATED_CLASSIFICATION = "saturated"
OSCILLATING_CLASSIFICATION = "oscillating"
POOR_PERFORMANCE_CLASSIFICATION = "poor_performance"

FLATLINE_CODE = "flatline"
STICTION_CODE = "stiction"
NOISE_DRIVEN_CODE = "noise_driven"
TRAVEL_PARAM = "travel"
REVERSALS_PARAM = "reversals"
STICTION_TEST_ADVICE = "test_valve"
PERCENT_PARAM = "percent"
LOOPS_PARAM = "loops"
RATIO_PARAM = "ratio"
HINT_PARAM = "hint"
MISSING_PARAM = "missing"

# --- Priorities -------------------------------------------------------------

PROBLEM_URGENCY = 0
WARNING_URGENCY = 1
OTHER_URGENCY = 2
CONFIGURE_URGENCY = 3
NO_ACTION_URGENCY = 4
UNKNOWN_HEALTH = 101  # sorts unknown health after every real score in the same urgency band

STATUS_URGENCY = {"problem": PROBLEM_URGENCY, "warning": WARNING_URGENCY}
ADVICE_URGENCIES = {CONFIGURE_KNOWLEDGE: CONFIGURE_URGENCY, NO_ACTION: NO_ACTION_URGENCY}

Row = dict[str, Any]


def _action(code: str, params: dict[str, Any]) -> dict[str, Any]:
    """A next action as the JSON-ready dict the UI expects."""
    return {"code": code, "params": params}


def _finding_codes(row: Row) -> set[str]:
    """The codes of all findings of one row; an empty set when it has none."""
    findings = row.get("findings") or []
    return {
        str(finding.get("code")) if isinstance(finding, dict) else str(finding)
        for finding in findings
        if not isinstance(finding, dict) or finding.get("outcome") not in {"fixed", "not_a_problem"}
    }


def _is_manual(row: Row) -> bool:
    """True when the loop is classified as run by hand."""
    return (row.get("classification") == MANUAL_CLASSIFICATION
            or MANUAL_CLASSIFICATION in _finding_codes(row))


def _is_saturated(row: Row) -> bool:
    """True when the controller output sat at a limit."""
    return (row.get("classification") == SATURATED_CLASSIFICATION
            or SATURATED_CLASSIFICATION in _finding_codes(row))


def _is_oscillating(row: Row) -> bool:
    """True when the loop cycles around its setpoint."""
    return (row.get("classification") == OSCILLATING_CLASSIFICATION
            or OSCILLATING_CLASSIFICATION in _finding_codes(row))


def _is_flatlined(row: Row) -> bool:
    """True when the PV was reported frozen."""
    return FLATLINE_CODE in _finding_codes(row)


def _stiction_doubted(row: Row) -> bool:
    """True when the valve is suspected of sticking or was advised a valve test."""
    advised = row.get("stiction_advice") == STICTION_TEST_ADVICE
    return advised or STICTION_CODE in _finding_codes(row)


def _shared_period_loops(row: Row) -> list[str]:
    """The other loops cycling at the same period as this one, sorted by name."""
    peers = row.get("same_period_as") or []
    return sorted([peers] if isinstance(peers, str) else [str(name) for name in peers])


def _manual_params(row: Row) -> dict[str, Any]:
    """The share of time the loop ran outside automatic control, as a whole percent.

    An unknown service factor gives None, not "100 % manual".
    """
    service = _number_or_none(row.get("service_percent"))
    percent = None if service is None else 100 - round(service)
    return {PERCENT_PARAM: percent}


def _number_or_none(value: Any) -> float | None:
    """The value as a float, or None when it is missing, not a number or NaN."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _common_source_params(row: Row) -> dict[str, Any]:
    """The loops cycling together, which point at one disturbance to find before any retuning."""
    return {LOOPS_PARAM: _shared_period_loops(row)}


def _resolution_params(row: Row) -> dict[str, Any]:
    """A coarse output steps in visible jumps, so the cycle may be resolution, not tuning."""
    return {RATIO_PARAM: round(row["out_quantisation_ratio"], 1)}


def _sizing_params(row: Row) -> dict[str, Any]:
    """An oversized or undersized valve limits control whatever the tuning says."""
    return {HINT_PARAM: row["valve_sizing_hint"]}


def _configure_params(row: Row) -> dict[str, Any]:
    """Conclusions withheld for missing per-loop knowledge cannot be checked until it is given."""
    return {MISSING_PARAM: list(row.get("not_assessed") or [])}


def _is_noise_driven(row: Row) -> bool:
    """True when the overview found the valve moved by measurement noise."""
    return NOISE_DRIVEN_CODE in _finding_codes(row)


def _noise_params(row: Row) -> dict[str, Any]:
    """The valve travel (percent of span per hour) and reversals per hour behind the advice."""
    travel = _number_or_none(row.get("valve_travel_per_h"))
    reversals = _number_or_none(row.get("valve_reversals_per_h"))
    return {
        TRAVEL_PARAM: None if travel is None else round(travel),
        REVERSALS_PARAM: None if reversals is None else round(reversals),
    }


def _has_sizing_hint(row: Row) -> bool:
    """True when the valve sizing check produced a hint."""
    return row.get("valve_sizing_hint") is not None


def _has_coarse_output(row: Row) -> bool:
    """True when the output resolution is at or above the limiting ratio."""
    ratio = row.get("out_quantisation_ratio")
    return ratio is not None and ratio >= QUANTISATION_LIMITING


def _needs_knowledge(row: Row) -> bool:
    """True when at least one conclusion was withheld for missing knowledge."""
    return bool(row.get("not_assessed"))


# One rule: (applies?, action code, builder of the action parameters or None for no parameters).
Rule = tuple[Callable[[Row], bool], str, Callable[[Row], dict[str, Any]] | None]

def _has_direct_valve_evidence(row: Row) -> bool:
    """Separate measured valve faults from oscillation-based suspicions."""
    if row.get("valve_evidence") == "direct":
        return True
    return any(
        isinstance(finding, dict) and finding.get("code") in {"stiction", "deadband"}
        and finding.get("evidence") == "direct"
        and finding.get("outcome") not in {"fixed", "not_a_problem"}
        for finding in row.get("findings") or []
    )


# First unresolved cause wins: instrument, direct valve evidence, external cause,
# design/mode, then tuning. Oscillation alone does not prove a sticking valve.
RULES: tuple[Rule, ...] = (
    (_is_flatlined, CHECK_MEASUREMENT, None),
    (_is_noise_driven, REVIEW_NOISE_RESPONSE, _noise_params),
    (_is_saturated, CHECK_OUTPUT_LIMIT, None),
    (lambda row: bool(_finding_codes(row) & {"valve_stiction", "deadband"})
     or _has_direct_valve_evidence(row), VALVE_TEST, None),
    (_has_coarse_output, CHECK_OUTPUT_RESOLUTION, _resolution_params),
    (_has_sizing_hint, REVIEW_VALVE_SIZING, _sizing_params),
    (lambda row: bool(_shared_period_loops(row)) or bool(
        _finding_codes(row) & {"external_disturbance", "external_cause", "equipment_anomaly"}
    ), FIND_COMMON_SOURCE, _common_source_params),
    (_is_manual, ASK_WHY_MANUAL, _manual_params),
    (lambda row: _is_oscillating(row) and _stiction_doubted(row), VALVE_TEST, None),
    (_is_oscillating, TEST_CYCLE_CAUSE, None),
    (_needs_knowledge, CONFIGURE_KNOWLEDGE, _configure_params),
    (lambda row: row.get("classification") == POOR_PERFORMANCE_CLASSIFICATION,
     BUMP_TEST_AND_RETUNE, None),
)

ACTION_STEPS = {
    CHECK_MEASUREMENT: "instrument", REVIEW_NOISE_RESPONSE: "instrument",
    CHECK_OUTPUT_LIMIT: "valve", VALVE_TEST: "valve",
    CHECK_OUTPUT_RESOLUTION: "valve", REVIEW_VALVE_SIZING: "valve",
    FIND_COMMON_SOURCE: "external_cause", TEST_CYCLE_CAUSE: "external_cause",
    ASK_WHY_MANUAL: "design_or_mode", CONFIGURE_KNOWLEDGE: "design_or_mode",
    BUMP_TEST_AND_RETUNE: "tuning", NO_ACTION: "none",
}
CRITICALITY_WEIGHTS = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}
NEUTRAL_FACTOR = 1.0  # dimensionless fallback when site knowledge is absent
STATUS_SEVERITY = {"problem": 3.0, "warning": 2.0}  # dimensionless ordinal weights
HEALTH_SPAN = 100.0  # percentage points in a completely healthy loop


def _positive_factor(value: Any) -> float:
    """Use nonnegative finite factors; missing inputs remain neutral."""
    number = _number_or_none(value)
    return NEUTRAL_FACTOR if number is None else max(0.0, number)


def _rank_factors(row: Row) -> dict[str, float]:
    """Read severity, catalogue consequence and the existing economic estimate."""
    knowledge = row.get("knowledge") or {}
    criticality = row.get("criticality", knowledge.get(
        "criticality", row.get("equipment_criticality")))
    benefit = row.get("benefit") or {}
    estimate = benefit.get("estimate", benefit) if isinstance(benefit, dict) else {}
    health = _number_or_none(row.get("health_percent"))
    severity = STATUS_SEVERITY.get(row.get("status"), NEUTRAL_FACTOR)
    if health is not None:
        severity += max(0.0, HEALTH_SPAN - health) / HEALTH_SPAN
    if row["next_action"]["code"] == NO_ACTION and not _finding_codes(row):
        severity = 0.0
    return {
        "severity": _positive_factor(row.get("severity", severity)),
        "criticality": CRITICALITY_WEIGHTS.get(criticality, _positive_factor(criticality)),
        "benefit": _positive_factor(estimate.get("value_per_h", row.get("value_per_h",
            benefit if not isinstance(benefit, dict) else None))),
    }


def next_action(row: Row) -> dict[str, Any]:
    """The first advice that applies to one overview row, as a dict with "code" and "params".

    Missing or None row values are tolerated, so rows written by an older overview version still
    get an answer.

    Returns:
        One action dict; the fallback, when no rule applies, is NO_ACTION with no parameters.
    """
    for applies, code, build_params in RULES:
        if applies(row):
            return _action(code, build_params(row) if build_params is not None else {})
    return _action(NO_ACTION, {})


def _urgency(row: Row) -> int:
    """Priority band of one row: 0 is looked at first, 4 last."""
    status = row.get("status")
    if status in STATUS_URGENCY:
        return STATUS_URGENCY[status]
    return ADVICE_URGENCIES.get(row["next_action"]["code"], OTHER_URGENCY)


def _health(row: Row) -> int:
    """Health score used as tie-breaker, or UNKNOWN_HEALTH when it is missing."""
    health = _number_or_none(row.get("health_percent"))
    return UNKNOWN_HEALTH if health is None else int(health)


def priority_key(row: Row) -> tuple[float, str, str]:
    """Rank descending product, then ascending catalogue id and loop name."""
    return (-row["rank_score"], str(row.get("id", row.get("name", ""))),
            str(row.get("name", "")))


def add_worklist(rows: list[Row]) -> None:
    """Attach rank factors, diagnosis step, next action and a one-based priority."""
    for row in rows:
        row["next_action"] = next_action(row)
        row["diagnosis_step"] = ACTION_STEPS[row["next_action"]["code"]]
        factors = _rank_factors(row)
        row["rank_factors"] = factors
        # Model: score = severity ? criticality ? benefit. Rows are JSON dictionaries;
        # severity/consequence are dimensionless and benefit is site currency/hour
        # when priced, otherwise neutral 1. Scores are comparable within one site.
        row["rank_score"] = math.prod(factors.values())
    for rank, row in enumerate(sorted(rows, key=priority_key), start=1):
        row["priority_rank"] = rank
