"""Tests for the pure operating-mode evaluator (#146): precedence, unknown, stopped exclusion."""

import numpy as np
from crosscut_connectors import mode_eval

SITE = {
    "equipment": [
        {"id": "area", "level": "area"},
        {"id": "mill", "level": "equipment", "parent": "area",
         "running": {"tag": "RUN", "above": 1.0, "confirmed": True}},
    ],
    "modes": [
        {"id": "normal", "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 50}]}},
        {"id": "high", "scope": "mill",
         "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 150}]}},
        {"id": "stopped", "condition": {"clauses": [{"tag": "SPEED", "op": "<", "value": 1}]}},
        {"id": "other", "scope": "elsewhere",
         "condition": {"clauses": [{"tag": "FEED", "op": ">", "value": 0}]}},
    ],
}


def _labels(**data: list[float]) -> list[str]:
    count = len(next(iter(data.values())))
    return [str(x) for x in mode_eval.evaluate(SITE, "mill", data, count)]


def test_scope_specificity_beats_catalogue_order() -> None:
    """A mode scoped to the equipment wins over a site-wide mode that also holds."""
    assert _labels(FEED=[100.0, 200.0], SPEED=[5.0, 5.0]) == ["normal", "high"]


def test_stopped_wins_within_its_scope_and_foreign_scope_is_ignored() -> None:
    """``stopped`` precedes the other site-wide modes; a mode of another equipment never applies."""
    ids = [m["id"] for m in mode_eval.applicable_modes(SITE, "mill")]
    assert ids == ["high", "stopped", "normal"]
    assert _labels(FEED=[100.0], SPEED=[0.0]) == ["stopped"]


def test_missing_input_is_unknown_not_a_lower_mode() -> None:
    """Unknown inputs of a higher-precedence mode make the sample unknown."""
    assert _labels(FEED=[np.nan, 100.0], SPEED=[5.0, 5.0]) == ["unknown", "normal"]
    assert _labels(SPEED=[5.0]) == ["unknown"]  # FEED tag absent altogether


def test_no_match_is_none_and_any_match_logic() -> None:
    """All-false gives ``none``; ``any`` holds when one clause does, others unknown."""
    assert _labels(FEED=[10.0], SPEED=[5.0]) == ["none"]
    site = {"modes": [{"id": "m", "condition": {"match": "any", "clauses": [
        {"tag": "A", "op": ">", "value": 1}, {"tag": "B", "op": ">", "value": 1}]}}]}
    out = mode_eval.evaluate(site, None, {"A": [5.0, 0.0], "B": [np.nan, np.nan]}, 2)
    assert [str(x) for x in out] == ["m", "unknown"]


def test_stopped_mask_by_mode_or_running_signal() -> None:
    """Stopped samples are the ``stopped`` mode or a running signal at/below its threshold."""
    data = {"FEED": [100.0, 100.0, 100.0], "SPEED": [0.0, 5.0, 5.0], "RUN": [5.0, 0.5, np.nan]}
    labels = mode_eval.evaluate(SITE, "mill", data, 3)
    off = mode_eval.not_running(SITE, "mill", data, 3)
    assert mode_eval.stopped_mask(labels, off).tolist() == [True, True, False]


def test_evaluate_row_and_owner() -> None:
    """The scalar wrapper agrees with the vector evaluator; the owner is the listing equipment."""
    row = {"FEED": 100.0, "SPEED": 5.0, "RUN": 5.0}
    assert mode_eval.evaluate_row(SITE, "mill", row) == ("normal", False)
    assert mode_eval.evaluate_row(SITE, "mill", {**row, "RUN": 0.0}) == ("normal", True)
    site = {"equipment": [{"id": "mill", "level": "equipment", "loops": ["fic"]}]}
    assert mode_eval.owner_of_loop(site, "fic") == "mill"
    assert mode_eval.owner_of_loop(site, "x") is None
