"""Tests for the controllers[] section of the site catalogue: schema and cross-reference checks."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from crosscut_connectors.site import validate_site

ROOT = Path(__file__).resolve().parents[2]
BASE: dict[str, Any] = json.loads(
    (ROOT / "docs/examples/generic_concentrator/_site/site.json").read_text(encoding="utf-8")
)
SCHEMA: dict[str, Any] = json.loads((ROOT / "schemas/site.schema.json").read_text(encoding="utf-8"))
Mutation = Callable[[dict[str, Any]], None]


def _variables(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return doc["controllers"][0]["variables"]  # type: ignore[no-any-return]


def _by_role(doc: dict[str, Any], role: str) -> dict[str, Any]:
    return next(var for var in _variables(doc) if var["role"] == role)


def _problems(mutate: Mutation) -> list[str]:
    doc = copy.deepcopy(BASE)
    mutate(doc)
    return validate_site(doc)


def _dup_controller(doc: dict[str, Any]) -> None:
    doc["controllers"].append(copy.deepcopy(doc["controllers"][0]))


def _dup_variable(doc: dict[str, Any]) -> None:
    _variables(doc)[1]["id"] = _variables(doc)[0]["id"]


def _unknown_loop(doc: dict[str, Any]) -> None:
    _by_role(doc, "MV")["binding"] = {"loop": "NO.LOOP"}


def _unknown_tag(doc: dict[str, Any]) -> None:
    _by_role(doc, "CV")["binding"] = {"tag": "NO.TAG"}


def _mv_with_tag(doc: dict[str, Any]) -> None:
    _by_role(doc, "MV")["binding"] = {"tag": "CR1.POWER.PV"}


def _loop_without_mode(doc: dict[str, Any]) -> None:
    del doc["loops"][2]["mode"]  # CR1.FEED


def _eng_outside_validity(doc: dict[str, Any]) -> None:
    _by_role(doc, "CV")["limits"]["eng"] = {"lo": -5, "hi": 150}


def _operator_outside_eng(doc: dict[str, Any]) -> None:
    _by_role(doc, "CV")["limits"]["operator"] = {"lo": 20, "hi": 160}


def _inverted_pair(doc: dict[str, Any]) -> None:
    _by_role(doc, "CV")["limits"]["operator"] = {"lo": 90, "hi": 90}


def _move_on_cv(doc: dict[str, Any]) -> None:
    _by_role(doc, "CV")["limits"]["move_max"] = 1


def _required_dv(doc: dict[str, Any]) -> None:
    _by_role(doc, "DV")["required"] = True


def _no_cv(doc: dict[str, Any]) -> None:
    doc["controllers"][0]["variables"] = [v for v in _variables(doc) if v["role"] != "CV"]


def _no_mv(doc: dict[str, Any]) -> None:
    doc["controllers"][0]["variables"] = [v for v in _variables(doc) if v["role"] != "MV"]


CASES: list[tuple[Mutation, str]] = [
    (_dup_controller, "controllers: duplicate id 'CR1.SUP'"),
    (_dup_variable, "controllers.0.variables: duplicate id 'feed'"),
    (_unknown_loop, "binding: unknown loop 'NO.LOOP'"),
    (_unknown_tag, "binding: unknown tag 'NO.TAG'"),
    (_mv_with_tag, "binding: an MV needs a loop"),
    (_loop_without_mode, "binding: loop 'CR1.FEED' has no mode tag"),
    (_eng_outside_validity, "limits.eng: must lie within validity"),
    (_operator_outside_eng, "limits.operator: must lie within eng"),
    (_inverted_pair, "limits.operator: lo must be below hi"),
    (_move_on_cv, "limits.move_max: only an MV has move_max"),
    (_required_dv, "required: only an MV can be required"),
    (_no_cv, "needs at least one CV"),
    (_no_mv, "needs at least one MV"),
]


def test_example_controller_is_valid() -> None:
    assert validate_site(copy.deepcopy(BASE)) == []
    assert BASE["controllers"][0]["type"] == "fuzzy"


@pytest.mark.parametrize(("mutate", "expected"), CASES, ids=[c[0].__name__ for c in CASES])
def test_invalid_controller_names_the_problem(mutate: Mutation, expected: str) -> None:
    problems = _problems(mutate)
    assert any(expected in line for line in problems), problems


def test_rule_base_is_only_an_id() -> None:
    def blank(doc: dict[str, Any]) -> None:
        doc["controllers"][0]["rule_base"] = ""

    assert _problems(blank)


def test_schema_ranges_and_documented_defaults() -> None:
    props = SCHEMA["$defs"]["controller"]["properties"]
    assert (props["cycle_s"]["minimum"], props["cycle_s"]["maximum"]) == (1, 3600)
    assert props["type"]["enum"] == ["fuzzy"]
    for name, default in (("cycle_s", "30"), ("stale_cycles", "3"), ("max_overruns", "3")):
        assert f"{default} when omitted" in props[name]["description"]


def test_optional_fields_may_be_omitted() -> None:
    def strip(doc: dict[str, Any]) -> None:
        for key in ("cycle_s", "stale_cycles", "max_overruns", "rule_base", "description"):
            del doc["controllers"][0][key]

    assert _problems(strip) == []


@pytest.mark.parametrize("cycle", [0.5, 3601])
def test_cycle_out_of_range_fails_schema(cycle: float) -> None:
    def set_cycle(doc: dict[str, Any]) -> None:
        doc["controllers"][0]["cycle_s"] = cycle

    assert _problems(set_cycle)
