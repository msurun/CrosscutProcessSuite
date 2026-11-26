"""Tests for the naming-rules engine: presets, first-match-wins, conflicts, incomplete loops.

Synthetic tag names only. Each test compiles rules the way the API does and checks the
classification result, the tree handed to the catalogue import, and the rule compile errors.
"""

from __future__ import annotations

import pytest
from crosscut_connectors.naming_rules import PRESETS, apply_rules, compile_rules


def _rules(name: str) -> list:
    """Compiled rules of a built-in preset."""
    return compile_rules(PRESETS[name])


def test_isa_suffix_preset_classifies_loop_roles() -> None:
    """FIC-101.PV/.SP/.OP form one loop; LIC-201_PV uses the underscore delimiter."""
    result = apply_rules(
        _rules("isa_suffix"), ["FIC-101.PV", "FIC-101.SP", "FIC-101.OP", "LIC-201_PV"]
    )
    assert result.loops == {
        "FIC-101": {"pv": "FIC-101.PV", "sp": "FIC-101.SP", "out": "FIC-101.OP"},
        "LIC-201": {"pv": "LIC-201_PV"},
    }
    assert result.unmatched == []


def test_isa_suffix_maps_mv_to_pv_and_mode_stays_mode() -> None:
    """MV is a measured value alias of PV; MODE keeps its own role."""
    result = apply_rules(_rules("isa_suffix"), ["TIC-301.MV", "TIC-301.MODE"])
    assert result.loops["TIC-301"] == {"pv": "TIC-301.MV", "mode": "TIC-301.MODE"}


def test_area_equipment_signal_preset_builds_area_and_equipment() -> None:
    """200-PP-101-CURRENT gives area 200, equipment PP-101 and a plain signal."""
    result = apply_rules(_rules("area_equipment_signal"), ["200-PP-101-CURRENT"])
    (match,) = result.matches
    assert (match.area, match.equipment, match.signal, match.loop) == (
        "200",
        "PP-101",
        "CURRENT",
        None,
    )
    assert result.tree["200"]["PP-101"]["signals"] == ["200-PP-101-CURRENT"]


def test_first_matching_rule_wins() -> None:
    """The earlier rule takes the tag, so its role override applies, not the later rule's."""
    rules = compile_rules(
        [
            {"pattern": r"^(?P<loop>[A-Z]+-\d+)\.(?P<role>PV)$", "roles": {"pv": "sp"}},
            {"pattern": r"^(?P<loop>[A-Z]+-\d+)\.(?P<role>PV)$"},
        ]
    )
    match = apply_rules(rules, ["FIC-101.PV"]).matches[0]
    assert (match.rule, match.role) == (0, "sp")


def test_two_tags_for_one_loop_role_are_a_conflict() -> None:
    """Both tags are listed, and the first one keeps the loop slot."""
    result = apply_rules(_rules("isa_suffix"), ["FIC-101.PV", "FIC-101_PV"])
    assert result.conflicts == [
        {"loop": "FIC-101", "role": "pv", "tags": ["FIC-101.PV", "FIC-101_PV"]}
    ]
    assert result.loops["FIC-101"]["pv"] == "FIC-101.PV"


def test_loop_missing_sp_is_incomplete() -> None:
    """A loop with PV and OUT but no SP reports only sp as missing."""
    result = apply_rules(_rules("isa_suffix"), ["FIC-101.PV", "FIC-101.OP"])
    assert result.incomplete == [{"loop": "FIC-101", "missing": ["sp"]}]


def test_loop_with_only_pv_misses_out_and_sp() -> None:
    """A lone PV leaves out and sp missing, in PV, OUT, SP order."""
    result = apply_rules(_rules("isa_suffix"), ["FIC-101.PV"])
    assert result.incomplete == [{"loop": "FIC-101", "missing": ["out", "sp"]}]


def test_tag_without_a_rule_is_unmatched() -> None:
    """A name no rule accepts lands in unmatched and nowhere else."""
    result = apply_rules(_rules("isa_suffix"), ["junk_tag"])
    assert result.unmatched == ["junk_tag"]
    assert result.matches == [] and result.loops == {}


def test_loop_without_area_is_listed_once_in_the_blank_bucket() -> None:
    """Loop tags with no area or equipment group share one blank bucket, loop listed once."""
    result = apply_rules(_rules("isa_suffix"), ["FIC-101.PV", "FIC-101.SP", "FIC-101.OP"])
    assert result.tree == {"": {"": {"loops": ["FIC-101"], "signals": []}}}


def test_signal_without_area_uses_blank_area_bucket_and_equipment() -> None:
    """An equipment-only rule without area puts its signal under the blank area."""
    rules = compile_rules([{"pattern": r"^(?P<equipment>[A-Z]+-\d+)_(?P<signal>\w+)$"}])
    result = apply_rules(rules, ["PP-101_RUN"])
    assert result.tree == {"": {"PP-101": {"loops": [], "signals": ["PP-101_RUN"]}}}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([{"pattern": "("}], "invalid pattern"),
        ([{"pattern": r"^(?P<loop>\w+)\.(?P<tag>\w+)$"}], "unknown named groups: tag"),
        ([{"pattern": r"^(?P<role>PV)$"}], "must have a 'loop' or 'equipment' group"),
    ],
)
def test_bad_rules_raise_value_error(raw: list, message: str) -> None:
    """Invalid regex, an unknown group name and a missing loop or equipment group all fail."""
    with pytest.raises(ValueError, match=message):
        compile_rules(raw)


def test_roles_override_map_replaces_the_suffix_default() -> None:
    """A rule's lowercase roles key re-maps a suffix instead of the built-in role."""
    rules = compile_rules(
        [{"pattern": r"^(?P<loop>\w+-\d+)\.(?P<role>\w+)$", "roles": {"fb": "sp"}}]
    )
    match = apply_rules(rules, ["FIC-101.fb"]).matches[0]
    assert match.role == "sp"


def test_roles_override_with_uppercase_key_is_applied() -> None:
    """An uppercase roles key overrides the role like a lowercase one."""
    rules = compile_rules(
        [{"pattern": r"^(?P<loop>\w+-\d+)\.(?P<role>\w+)$", "roles": {"OP": "sp"}}]
    )
    assert apply_rules(rules, ["FIC-101.OP"]).matches[0].role == "sp"
