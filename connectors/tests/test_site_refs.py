"""Tests for crosscut_connectors.site_refs: cross-reference checks of the site catalogue.

Each case breaks one reference of the example site file and expects one readable problem line.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from crosscut_connectors.site import validate_site
from crosscut_connectors.site_refs import convertible

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/generic_concentrator/_site/site.json"
BASE: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
Mutation = Callable[[dict[str, Any]], None]


def _equipment(doc: dict[str, Any], ident: str) -> dict[str, Any]:
    return next(entry for entry in doc["equipment"] if entry["id"] == ident)


def _loop_with_sp(doc: dict[str, Any]) -> dict[str, Any]:
    return next(loop for loop in doc["loops"] if "sp" in loop)


def _unknown_pv(doc: dict[str, Any]) -> None:
    doc["loops"][0]["pv"] = "NO.SUCH.TAG"


def _cascade_without_loop(doc: dict[str, Any]) -> None:
    doc["loops"][0]["links"] = [{"kind": "cascade"}]


def _feedforward_without_tag(doc: dict[str, Any]) -> None:
    doc["loops"][0]["links"] = [{"kind": "feedforward"}]


def _link_to_unknown_loop(doc: dict[str, Any]) -> None:
    doc["loops"][0]["links"] = [{"kind": "ratio", "loop": "NO.LOOP"}]


def _unknown_parent(doc: dict[str, Any]) -> None:
    _equipment(doc, "ML1")["parent"] = "NOWHERE"


def _parent_cycle(doc: dict[str, Any]) -> None:
    _equipment(doc, "CR1")["parent"] = "SCR1"
    _equipment(doc, "SCR1")["parent"] = "CR1"


def _unit_without_parent(doc: dict[str, Any]) -> None:
    del _equipment(doc, "ML1")["parent"]


def _parent_at_same_level(doc: dict[str, Any]) -> None:
    _equipment(doc, "SCR1")["parent"] = "CR1"


def _tag_in_two_entries(doc: dict[str, Any]) -> None:
    _equipment(doc, "CR1")["tags"].append(_equipment(doc, "SCR1")["tags"][0])


def _duplicate_equipment_id(doc: dict[str, Any]) -> None:
    doc["equipment"].append(copy.deepcopy(_equipment(doc, "CR1")))


def _loop_signal_without_loop(doc: dict[str, Any]) -> None:
    next(s for s in doc["signals"] if s["role"] == "pv").pop("loop")


def _signal_unknown_loop(doc: dict[str, Any]) -> None:
    next(s for s in doc["signals"] if s["role"] == "sp")["loop"] = "NO.LOOP"


def _signal_disagrees_with_loop(doc: dict[str, Any]) -> None:
    first = next(s for s in doc["signals"] if s["role"] == "pv")
    other = next(s for s in doc["signals"] if s["role"] == "pv" and s is not first)
    first["tag"] = other["tag"]


def _lab_unknown_tag(doc: dict[str, Any]) -> None:
    doc["labs"][0]["tag"] = "NO.SUCH.TAG"


def _lab_unit_not_convertible(doc: dict[str, Any]) -> None:
    doc["labs"][0]["unit"] = "mm"
    doc["units"] = {"conversions": []}


def _mode_unknown_scope(doc: dict[str, Any]) -> None:
    doc["modes"][0]["scope"] = "NOWHERE"


def _mode_unknown_clause_tag(doc: dict[str, Any]) -> None:
    doc["modes"][0]["condition"]["clauses"][0]["tag"] = "NO.SUCH.TAG"


def _pv_sp_units_differ(doc: dict[str, Any]) -> None:
    loop = _loop_with_sp(doc)
    next(t for t in doc["tags"] if t["id"] == loop["pv"])["unit"] = "zzz"


CASES = [
    (_unknown_pv, "unknown tag"),
    (_cascade_without_loop, "needs a loop"),
    (_feedforward_without_tag, "needs a tag"),
    (_link_to_unknown_loop, "unknown loop"),
    (_unknown_parent, "unknown equipment"),
    (_parent_cycle, "cycle"),
    (_unit_without_parent, "needs a parent"),
    (_parent_at_same_level, "must be above"),
    (_tag_in_two_entries, "already attached"),
    (_duplicate_equipment_id, "duplicate id"),
    (_loop_signal_without_loop, "needs a loop"),
    (_signal_unknown_loop, "unknown loop"),
    (_signal_disagrees_with_loop, "not"),
    (_lab_unknown_tag, "unknown tag"),
    (_lab_unit_not_convertible, "cannot be converted"),
    (_mode_unknown_scope, "unknown equipment"),
    (_mode_unknown_clause_tag, "unknown tag"),
    (_pv_sp_units_differ, "cannot be converted"),
]


def test_example_site_has_no_problems() -> None:
    assert validate_site(BASE) == []


@pytest.mark.parametrize(("mutate", "expected"), CASES, ids=[c[0].__name__ for c in CASES])
def test_broken_reference_is_reported(mutate: Mutation, expected: str) -> None:
    doc = copy.deepcopy(BASE)
    mutate(doc)
    problems = validate_site(doc)
    assert any(expected in line for line in problems), problems


def test_lab_unit_converts_through_a_chain() -> None:
    doc = copy.deepcopy(BASE)
    doc["labs"][0]["unit"] = "x"
    doc["units"] = {
        "conversions": [
            {"from": "um", "to": "x", "factor": 2},
            {"from": "x", "to": "mm", "factor": 0.0005},
        ]
    }
    assert validate_site(doc) == []


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [("a", "a", True), ("b", "a", True), ("a", "c", True), ("a", "d", False)],
)
def test_convertible(source: str, target: str, expected: bool) -> None:
    conversions = [
        {"from": "a", "to": "b", "factor": 2},
        {"from": "b", "to": "c", "factor": 3},
    ]
    assert convertible(source, target, conversions) is expected
