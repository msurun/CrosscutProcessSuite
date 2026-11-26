"""Exercise condition proposals and equipment catalogue references.

Synthetic equipment isolates ownership rules from source-specific naming conventions.
"""

import pytest
from crosscut_connectors.condition_signals import (
    one_loop_equipment,
    propose_kind,
    propose_running,
)
from crosscut_connectors.site_refs import reference_problems


@pytest.mark.parametrize(
    ("unit", "kind"),
    [("degC", "temperature"), ("°C", "temperature"), ("K", "temperature"),
     ("degF", "temperature"), ("A", "current"), ("mA", "current"), ("kA", "current"),
     ("kW", "power"), ("W", "power"), ("MW", "power"), ("hp", "power"),
     ("Nm", "torque"), ("kNm", "torque"), ("mm/s", "vibration"),
     ("in/s", "vibration"), ("g", "vibration"), ("um", "vibration"),
     ("rpm", "speed"), ("1/min", "speed")],
)
def test_units_take_precedence_over_keywords(unit: str, kind: str) -> None:
    """Engineering units override contradictory names and descriptions."""
    assert propose_kind("200-PP-101-AMB", unit, "vibration") == kind


@pytest.mark.parametrize(
    ("keyword", "kind"),
    [("TEMP", "temperature"), ("TT", "temperature"), ("BRG", "temperature"),
     ("CURR", "current"), ("AMP", "current"), ("IT", "current"),
     ("POWER", "power"), ("JT", "power"), ("TORQ", "torque"),
     ("VIB", "vibration"), ("VT", "vibration"), ("SPEED", "speed"),
     ("ST", "speed"), ("RPM", "speed"), ("AMB", "ambient")],
)
def test_names_supply_case_insensitive_hints(keyword: str, kind: str) -> None:
    """Instrument codes and name keywords propose the expected role."""
    assert propose_kind(f"200-PP-101-{keyword.lower()}101", None, None) == kind


def test_description_supplies_a_hint() -> None:
    """Descriptions can identify a signal when the name is opaque."""
    assert propose_kind("200-PP-101-X", None, "motor current") == "current"


@pytest.mark.parametrize("name", ["200-PP-101-SPEED", "200-PP-101-freq"])
def test_frequency_units_need_a_speed_or_frequency_name(name: str) -> None:
    """Hertz is a speed hint only with supporting name metadata."""
    assert propose_kind(name, "Hz", None) == "speed"


@pytest.mark.parametrize("unit", [None, "bar", "Hz"])
def test_unknown_metadata_has_no_proposal(unit: str | None) -> None:
    """Unknown metadata remains unclassified instead of inventing a role."""
    assert propose_kind("200-PP-101-QUALITY", unit, None) is None


def test_running_prefers_speed_even_when_current_is_first() -> None:
    """Speed takes precedence independently of input order."""
    signals = [{"tag": "200-PP-101-CURRENT", "kind": "current"},
               {"tag": "200-PP-101-SPEED", "kind": "speed"}]
    assert propose_running(signals) == {
        "tag": "200-PP-101-SPEED", "above": 10.0, "confirmed": False,
    }


def test_running_falls_back_to_current() -> None:
    """Current uses the default threshold in amperes."""
    assert propose_running([{"tag": "200-PP-101-CURRENT", "kind": "current"}]) == {
        "tag": "200-PP-101-CURRENT", "above": 1.0, "confirmed": False,
    }


@pytest.mark.parametrize("signals", [[], [{"tag": "200-PP-101-TEMP", "kind": "temperature"}]])
def test_running_needs_a_current_or_speed_signal(signals: list[dict]) -> None:
    """Unsupported condition signals cannot establish running state."""
    assert propose_running(signals) is None


def test_an_unowned_loop_gets_minimal_equipment() -> None:
    """Fallback equipment uses the loop id as its stable identity."""
    assert one_loop_equipment("200-FIC-101") == {
        "id": "200-FIC-101", "level": "equipment", "loops": ["200-FIC-101"],
    }


def catalogue() -> dict:
    """Return a valid synthetic hierarchy with a primary loop owner."""
    return {
        "tags": [{"id": "200-PP-101-CURRENT"}],
        "loops": [{"id": "200-FIC-101", "pv": "200-PP-101-CURRENT",
                   "out": "200-PP-101-CURRENT"}],
        "equipment": [{"id": "200", "level": "site"},
                      {"id": "200-PP-101", "level": "equipment", "parent": "200",
                       "loops": ["200-FIC-101"]}],
    }


@pytest.mark.parametrize("field", ["loops", "loop_refs"])
def test_unknown_equipment_loops_are_reported(field: str) -> None:
    """Both primary and shared loop references must resolve."""
    document = catalogue()
    document["equipment"][1][field] = ["200-FIC-999"]
    assert reference_problems(document) == [f"equipment.1.{field}: unknown loop '200-FIC-999'"]


def test_two_primary_owners_are_reported() -> None:
    """A loop can belong primarily to only one equipment."""
    document = catalogue()
    document["equipment"].append({"id": "200-PP-102", "level": "equipment", "parent": "200",
                                  "loops": ["200-FIC-101"]})
    assert reference_problems(document) == [
        "equipment.2.loops: loop '200-FIC-101' already has primary owner '200-PP-101'",
    ]


def test_shared_loop_references_allow_another_primary_owner() -> None:
    """Sharing relevance does not claim primary ownership."""
    document = catalogue()
    document["equipment"][0]["loop_refs"] = ["200-FIC-101"]
    assert reference_problems(document) == []


def test_unknown_condition_signal_tags_are_reported() -> None:
    """Condition proposals still need known catalogue tags."""
    document = catalogue()
    document["equipment"][1]["signals"] = [
        {"tag": "200-PP-999-CURRENT", "kind": "current", "confirmed": False},
    ]
    assert reference_problems(document) == [
        "equipment.1.signals.0.tag: unknown tag '200-PP-999-CURRENT'",
    ]


def test_unknown_running_tags_are_reported() -> None:
    """Running rules cannot refer to a missing tag."""
    document = catalogue()
    document["equipment"][1]["running"] = {
        "tag": "200-PP-999-SPEED", "above": 10.0, "confirmed": False,
    }
    assert reference_problems(document) == [
        "equipment.1.running.tag: unknown tag '200-PP-999-SPEED'",
    ]
