"""Turn an overview's per-loop rows into a prioritised worklist: one next action per loop.

The ordering here is a rule of thumb for advice, not a validated score: saying which fix comes
first would need a blind review by a control engineer on real plant data. Until then, this module
only says what to look at next, and in which order.
"""

from __future__ import annotations

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
    return {str(finding.get("code")) for finding in (row.get("findings") or [])}


def _is_manual(row: Row) -> bool:
    """True when the loop is classified as run by hand."""
    return row.get("classification") == MANUAL_CLASSIFICATION


def _is_saturated(row: Row) -> bool:
    """True when the controller output sat at a limit."""
    return row.get("classification") == SATURATED_CLASSIFICATION


def _is_oscillating(row: Row) -> bool:
    """True when the loop cycles around its setpoint."""
    return row.get("classification") == OSCILLATING_CLASSIFICATION


def _is_flatlined(row: Row) -> bool:
    """True when the PV was reported frozen."""
    return FLATLINE_CODE in _finding_codes(row)


def _stiction_doubted(row: Row) -> bool:
    """True when the valve is suspected of sticking or was advised a valve test."""
    advised = row.get("stiction_advice") == STICTION_TEST_ADVICE
    return advised or STICTION_CODE in _finding_codes(row)


def _shared_period_loops(row: Row) -> list[str]:
    """The other loops cycling at the same period as this one, sorted by name."""
    return sorted(str(name) for name in (row.get("same_period_as") or []))


def _build_manual(row: Row) -> dict[str, Any]:
    """The share of time the loop ran outside automatic control, as a whole percent."""
    return _action(ASK_WHY_MANUAL, {PERCENT_PARAM: 100 - int(row.get("service_percent") or 0)})


def _build_measurement(row: Row) -> dict[str, Any]:
    """A frozen reading is checked first; the row itself carries no further numbers."""
    return _action(CHECK_MEASUREMENT, {})


def _build_output_limit(row: Row) -> dict[str, Any]:
    """A saturated output is checked at the valve and the controller limits."""
    return _action(CHECK_OUTPUT_LIMIT, {})


def _build_valve_test(row: Row) -> dict[str, Any]:
    """A sticking valve looks like a cycle but is fixed by maintenance, not by tuning."""
    return _action(VALVE_TEST, {})


def _build_common_source(row: Row) -> dict[str, Any]:
    """Loops cycling together point at one disturbance, to be found before retuning any of them."""
    return _action(FIND_COMMON_SOURCE, {LOOPS_PARAM: _shared_period_loops(row)})


def _build_cycle_cause(row: Row) -> dict[str, Any]:
    """A lone cycle: bump the loop and see whether the period changes (inside) or not (outside)."""
    return _action(TEST_CYCLE_CAUSE, {})


def _build_resolution(row: Row) -> dict[str, Any]:
    """A coarse output steps in visible jumps, so the cycle may be resolution, not tuning."""
    return _action(CHECK_OUTPUT_RESOLUTION, {RATIO_PARAM: round(row["out_quantisation_ratio"], 1)})


def _build_retune(row: Row) -> dict[str, Any]:
    """Poor performance without another explanation calls for a bump test and new tuning."""
    return _action(BUMP_TEST_AND_RETUNE, {})


def _build_sizing(row: Row) -> dict[str, Any]:
    """An oversized or undersized valve limits control whatever the tuning says."""
    return _action(REVIEW_VALVE_SIZING, {HINT_PARAM: row["valve_sizing_hint"]})


def _build_configure(row: Row) -> dict[str, Any]:
    """Conclusions withheld for missing per-loop knowledge cannot be checked until it is given."""
    return _action(CONFIGURE_KNOWLEDGE, {MISSING_PARAM: list(row.get("not_assessed") or [])})


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


# Rules in the order they are tried; the first match wins. The order is the only place that
# decides which advice outranks which, so each rule's comment says why it sits where it does.
RULES: tuple[tuple[Callable[[Row], bool], Callable[[Row], dict[str, Any]]], ...] = (
    # A manual loop is not controlled at all: nothing else can be judged until someone says why.
    (_is_manual, _build_manual),
    # A frozen reading makes every other finding untrustworthy, so it is checked before them.
    (_is_flatlined, _build_measurement),
    # The output pinned at a limit may be the real cause of a flatline or a cycle elsewhere.
    (_is_saturated, _build_output_limit),
    # A sticking valve must be fixed before any retuning, and before blaming a shared source.
    (lambda row: _is_oscillating(row) and _stiction_doubted(row), _build_valve_test),
    # One disturbance driving several loops is found before retuning any single one of them.
    (lambda row: _is_oscillating(row) and bool(_shared_period_loops(row)), _build_common_source),
    # A cycle nobody else sees is caused by the loop or by its process: a bump test tells which.
    (_is_oscillating, _build_cycle_cause),
    # Coarse output steps explain a small cycle, so they are checked before calling it poor tuning.
    (_has_coarse_output, _build_resolution),
    # Poor performance is the retuning case; every mechanical cause above is already excluded.
    (lambda row: row.get("classification") == POOR_PERFORMANCE_CLASSIFICATION, _build_retune),
    # A valve that is too big or too small limits control whatever the tuning: review it first.
    (_has_sizing_hint, _build_sizing),
    # Only when nothing is wrong: give the missing knowledge so the checks can run at all.
    (_needs_knowledge, _build_configure),
    # Nothing matched: the loop needs no action today.
    (lambda row: True, lambda row: _action(NO_ACTION, {})),
)


def next_action(row: Row) -> dict[str, Any]:
    """The first advice that applies to one overview row, as a dict with "code" and "params".

    Missing or None row values are tolerated, so rows written by an older overview version still
    get an answer.

    Returns:
        One action dict; the fallback is NO_ACTION with no parameters.
    """
    for applies, build in RULES:
        if applies(row):
            return build(row)
    return _action(NO_ACTION, {})  # unreachable: the last rule always matches


def _urgency(row: Row) -> int:
    """Priority band of one row: 0 is looked at first, 4 last."""
    status = row.get("status")
    if status in STATUS_URGENCY:
        return STATUS_URGENCY[status]
    return ADVICE_URGENCIES.get(row["next_action"]["code"], OTHER_URGENCY)


def _health(row: Row) -> int:
    """Health score used as tie-breaker, or UNKNOWN_HEALTH when it is missing."""
    health = row.get("health_percent")
    return UNKNOWN_HEALTH if health is None else int(health)


def priority_key(row: Row) -> tuple[int, int]:
    """Sort key of one row; smaller comes first.

    Expects ``row["next_action"]`` to be set already, which ``add_worklist`` guarantees.

    Returns:
        (urgency, health): the band first, then the worst health within that band.
    """
    return (_urgency(row), _health(row))


def add_worklist(rows: list[Row]) -> None:
    """Set ``next_action`` and ``priority_rank`` (1 = look first) on every row, in place.

    The sort is stable, so rows of equal priority keep their input order and equal rows do not
    swap places between two exports.
    """
    for row in rows:
        row["next_action"] = next_action(row)
    ordered = sorted(rows, key=priority_key)
    for rank, row in enumerate(ordered, start=1):
        row["priority_rank"] = rank
