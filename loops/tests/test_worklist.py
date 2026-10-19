"""Behaviour tests for crosscut_loops.worklist.

They pin the recommendation rules (first match wins, in the documented order) and
the ranking produced by add_worklist, including the health tie-breaks and the
stable input order. Every test builds its rows from _row(), so each test states
only the fields that matter to the behaviour under test.
"""

import pytest
from crosscut_loops import worklist as wl

# A healthy row: no findings, ok classification, full health. Overrides change one field.
_DEFAULT_ROW = {
    "name": "L1",
    "status": "ok",
    "health_percent": 90,
    "classification": "ok",
    "findings": [],
    "stiction_advice": "not_ranked",
    "same_period_as": [],
    "out_quantisation_ratio": None,
    "valve_sizing_hint": None,
    "not_assessed": [],
    "service_percent": 100,
}


def _row(**overrides):
    """Return a worklist row built from the defaults, with the given fields replaced."""
    return {**_DEFAULT_ROW, **overrides}


def _finding(code):
    """Return the smallest finding dict carrying the given diagnostic code."""
    return {"code": code}


# One minimal row per rule, with the expected code and params, in rule order.
_RULE_CASES = [
    ("manual", _row(classification="manual", service_percent=40),
     wl.ASK_WHY_MANUAL, {"percent": 60}),
    ("flatline", _row(findings=[_finding("flatline")]),
     wl.CHECK_MEASUREMENT, {}),
    ("saturated", _row(classification="saturated"),
     wl.CHECK_OUTPUT_LIMIT, {}),
    ("stiction", _row(classification="oscillating", stiction_advice="test_valve"),
     wl.VALVE_TEST, {}),
    ("common_source", _row(classification="oscillating", same_period_as=["L2"]),
     wl.FIND_COMMON_SOURCE, {"loops": ["L2"]}),
    ("oscillating", _row(classification="oscillating"),
     wl.TEST_CYCLE_CAUSE, {}),
    ("quantisation", _row(out_quantisation_ratio=1.25),
     wl.CHECK_OUTPUT_RESOLUTION, {"ratio": 1.2}),
    ("poor_performance", _row(classification="poor_performance"),
     wl.BUMP_TEST_AND_RETUNE, {}),
    ("sizing", _row(valve_sizing_hint="undersized"),
     wl.REVIEW_VALVE_SIZING, {"hint": "undersized"}),
    ("not_assessed", _row(not_assessed=["harris"]),
     wl.CONFIGURE_KNOWLEDGE, {"missing": ["harris"]}),
    ("none", _row(), wl.NO_ACTION, {}),
]


@pytest.mark.parametrize(
    "row, expected_action",
    [(case[1], {"code": case[2], "params": case[3]}) for case in _RULE_CASES],
    ids=[case[0] for case in _RULE_CASES],
)
def test_each_rule_produces_its_action(row, expected_action):
    """Each rule fires on a minimal row with its code and params."""
    assert wl.next_action(row) == expected_action


def test_manual_with_a_flatline_finding_asks_why_first():
    """The manual rule outranks a flatline finding."""
    row = _row(classification="manual", findings=[_finding("flatline")])
    assert wl.next_action(row)["code"] == wl.ASK_WHY_MANUAL


def test_flatline_outranks_oscillation():
    """A flatline finding is checked before the oscillation rules."""
    row = _row(classification="oscillating", findings=[_finding("flatline")])
    assert wl.next_action(row)["code"] == wl.CHECK_MEASUREMENT


def test_test_valve_advice_outranks_the_common_source_rule():
    """The valve test fires before the shared period search."""
    row = _row(classification="oscillating", stiction_advice="test_valve",
               same_period_as=["L2"])
    assert wl.next_action(row)["code"] == wl.VALVE_TEST


def test_shared_period_loops_are_sorted():
    """The common source params list the loops sorted by name."""
    row = _row(classification="oscillating", same_period_as=["B", "A"])
    assert wl.next_action(row)["params"] == {"loops": ["A", "B"]}


def test_a_quantisation_ratio_below_one_does_not_fire():
    """A ratio of 0.9 is below the threshold, so nothing is recommended."""
    assert wl.next_action(_row(out_quantisation_ratio=0.9))["code"] == wl.NO_ACTION


def test_a_row_with_only_a_name_gets_no_action():
    """Missing keys are treated as absent and never raise."""
    assert wl.next_action({"name": "X"}) == {"code": wl.NO_ACTION, "params": {}}


def test_add_worklist_ranks_by_urgency_then_health_then_action():
    """Problems come first, then warnings by health, then actionable and quiet rows."""
    rows = [
        _row(status="ok", health_percent=100),
        _row(status="warning", health_percent=50),
        _row(status="problem", health_percent=80),
        _row(status="warning", health_percent=30),
        _row(status="ok", health_percent=95, not_assessed=["harris"]),
        _row(status="ok", health_percent=70, out_quantisation_ratio=2.0),
    ]
    wl.add_worklist(rows)
    ranked_names = sorted(rows, key=lambda row: row["priority_rank"])
    expected_order = [rows[2], rows[3], rows[1], rows[5], rows[4], rows[0]]
    assert ranked_names == expected_order
    assert [row["priority_rank"] for row in rows] == [6, 3, 1, 2, 5, 4]


def test_unknown_health_sorts_after_known_health():
    """Within one urgency, a None health goes after every known health."""
    rows = [
        _row(name="unknown", status="warning", health_percent=None),
        _row(name="known", status="warning", health_percent=99),
    ]
    wl.add_worklist(rows)
    assert rows[0]["priority_rank"] == 2
    assert rows[1]["priority_rank"] == 1


def test_equal_ranks_keep_the_input_order():
    """Rows with identical keys keep their original position."""
    rows = [
        _row(name="first", status="problem", health_percent=50),
        _row(name="second", status="problem", health_percent=50),
    ]
    wl.add_worklist(rows)
    assert rows[0]["priority_rank"] == 1
    assert rows[1]["priority_rank"] == 2


def test_add_worklist_on_an_empty_list_does_nothing():
    """An empty worklist is left empty."""
    rows = []
    wl.add_worklist(rows)
    assert rows == []
