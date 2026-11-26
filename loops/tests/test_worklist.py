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


def test_instrument_finding_precedes_manual_mode():
    """Instrument checks precede design and mode checks."""
    row = _row(classification="manual", findings=[_finding("flatline")])
    assert wl.next_action(row)["code"] == wl.CHECK_MEASUREMENT


def test_flatline_outranks_oscillation():
    """A flatline finding is checked before the oscillation rules."""
    row = _row(classification="oscillating", findings=[_finding("flatline")])
    assert wl.next_action(row)["code"] == wl.CHECK_MEASUREMENT


def test_external_cause_precedes_an_indirect_valve_suspicion():
    """An indirect valve suspicion cannot override a known external cause."""
    row = _row(classification="oscillating", stiction_advice="test_valve",
               same_period_as=["L2"])
    assert wl.next_action(row)["code"] == wl.FIND_COMMON_SOURCE


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


@pytest.mark.parametrize("factor", ["severity", "criticality", "benefit"])
def test_increasing_a_factor_increases_the_score(factor):
    """Each multiplier increases priority while other factors stay fixed."""
    baseline = _row(name="base", severity=2, criticality=2, benefit={"value_per_h": 2})
    increased = {**baseline, "name": "increased"}
    increased[factor] = {"value_per_h": 3} if factor == "benefit" else 3
    wl.add_worklist([baseline, increased])
    assert increased["rank_score"] > baseline["rank_score"]
    assert increased["priority_rank"] == 1


def test_equal_scores_use_identity_regardless_of_input_order():
    """Catalogue identity resolves a tie deterministically."""
    rows = [_row(name="Z"), _row(name="A")]
    wl.add_worklist(rows)
    assert rows[1]["priority_rank"] == 1


def test_external_disturbance_with_oscillation_is_not_sent_to_a_valve_test():
    """Exp37's external forcing outranks a valve test inferred from oscillation."""
    row = _row(classification="oscillating", stiction_advice="test_valve",
               findings=[_finding("external_disturbance")])
    wl.add_worklist([row])
    assert row["diagnosis_step"] == "external_cause"
    assert row["next_action"]["code"] == wl.FIND_COMMON_SOURCE


def test_direct_valve_evidence_precedes_an_external_cause():
    """Observed mechanical evidence keeps the valve step ahead of external causes."""
    row = _row(valve_evidence="direct", findings=[_finding("external_disturbance")])
    wl.add_worklist([row])
    assert row["diagnosis_step"] == "valve"


def test_rank_score_is_the_product_of_documented_factors():
    """Catalogue criticality and the existing hourly estimate enter the product."""
    row = _row(severity=2, knowledge={"criticality": "high"},
               benefit={"estimate": {"value_per_h": 5}})
    wl.add_worklist([row])
    assert row["rank_factors"] == {"severity": 2, "criticality": 3, "benefit": 5}
    assert row["rank_score"] == 30


def test_unknown_health_sorts_after_known_health():
    """Within one urgency, a None health goes after every known health."""
    rows = [
        _row(name="unknown", status="warning", health_percent=None, classification="manual"),
        _row(name="known", status="warning", health_percent=99, classification="manual"),
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


@pytest.mark.parametrize("overrides, expected_step", [
    ({"findings": [{"code": "flatline"}], "valve_evidence": "direct"}, "instrument"),
    ({"valve_evidence": "direct", "same_period_as": ["source"]}, "valve"),
    ({"same_period_as": ["source"], "classification": "manual"}, "external_cause"),
    ({"classification": "manual"}, "design_or_mode"),
    ({"classification": "poor_performance"}, "tuning"),
])
def test_diagnosis_steps_follow_the_fixed_order(overrides, expected_step):
    """Earlier unresolved causes always precede later interventions."""
    row = _row(**overrides)
    wl.add_worklist([row])
    assert row["diagnosis_step"] == expected_step


def test_a_fixed_instrument_finding_does_not_hide_the_external_cause():
    """Resolved findings do not choose the next diagnostic step."""
    row = _row(findings=[{"code": "flatline", "outcome": "fixed"},
                         {"code": "external_disturbance"}])
    wl.add_worklist([row])
    assert row["diagnosis_step"] == "external_cause"


def test_direct_stiction_finding_precedes_the_external_cause():
    """Direct measured stiction differs from an oscillation-based suspicion."""
    row = _row(same_period_as=["source"], findings=[{"code": "stiction", "evidence": "direct"}])
    wl.add_worklist([row])
    assert row["diagnosis_step"] == "valve"
