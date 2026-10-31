"""Tests for the role mapping module (Phase 1, #37).

Verifies tag role suggestions across multiple plant naming conventions, legacy vocabulary
reconciliation, and loop assembly from signal tables.
"""

from __future__ import annotations

from crosscut_connectors.role_mapping import (
    canonical_role_from_legacy,
    loops_from_signals,
    suggest_roles,
)


def test_suggest_roles_for_dot_convention() -> None:
    tags = ["TIC101.PV", "TIC101.SP", "TIC101.OUT", "TIC101.MODE", "TIC101.FB"]
    signals = suggest_roles(tags)

    expected = [
        {"tag": "TIC101.PV", "role": "pv", "loop": "TIC101"},
        {"tag": "TIC101.SP", "role": "sp", "loop": "TIC101"},
        {"tag": "TIC101.OUT", "role": "out", "loop": "TIC101"},
        {"tag": "TIC101.MODE", "role": "mode", "loop": "TIC101"},
        {"tag": "TIC101.FB", "role": "fb", "loop": "TIC101"},
    ]
    assert signals == expected


def test_suggest_roles_for_underscore_convention() -> None:
    tags = ["FIC_202_pv", "FIC_202_sp", "FIC_202_out", "FIC_202_mode"]
    signals = suggest_roles(tags)

    expected = [
        {"tag": "FIC_202_pv", "role": "pv", "loop": "FIC_202"},
        {"tag": "FIC_202_sp", "role": "sp", "loop": "FIC_202"},
        {"tag": "FIC_202_out", "role": "out", "loop": "FIC_202"},
        {"tag": "FIC_202_mode", "role": "mode", "loop": "FIC_202"},
    ]
    assert signals == expected


def test_suggest_roles_for_dash_convention() -> None:
    tags = ["LIC-303-PV", "LIC-303-SP", "LIC-303-OUT", "LIC-303-MODE"]
    signals = suggest_roles(tags)

    expected = [
        {"tag": "LIC-303-PV", "role": "pv", "loop": "LIC-303"},
        {"tag": "LIC-303-SP", "role": "sp", "loop": "LIC-303"},
        {"tag": "LIC-303-OUT", "role": "out", "loop": "LIC-303"},
        {"tag": "LIC-303-MODE", "role": "mode", "loop": "LIC-303"},
    ]
    assert signals == expected


def test_suggest_roles_with_custom_naming_block() -> None:
    naming = {"valve_pattern": "V_{loop}_POS", "mode_suffix": "_AUTO"}
    tags = ["V_P101_POS", "P101_AUTO"]
    signals = suggest_roles(tags, naming=naming)

    expected = [
        {"tag": "V_P101_POS", "role": "out", "loop": "P101"},
        {"tag": "P101_AUTO", "role": "mode", "loop": "P101"},
    ]
    assert signals == expected


def test_suggest_roles_recognises_non_loop_inputs_targets_and_labs() -> None:
    tags = ["FEED_RATE", "PRESSURE_INLET", "P80_TARGET", "LAB_DENSITY", "LAB_MOISTURE"]
    signals = suggest_roles(tags)

    expected = [
        {"tag": "FEED_RATE", "role": "input"},
        {"tag": "PRESSURE_INLET", "role": "input"},
        {"tag": "P80_TARGET", "role": "target"},
        {"tag": "LAB_DENSITY", "role": "lab"},
        {"tag": "LAB_MOISTURE", "role": "lab"},
    ]
    assert signals == expected


def test_suggest_roles_recognises_disturbance_variable() -> None:
    tags = ["TIC101.DV", "TIC101_DIST"]
    signals = suggest_roles(tags)

    expected = [
        {"tag": "TIC101.DV", "role": "dv", "loop": "TIC101"},
        {"tag": "TIC101_DIST", "role": "dv", "loop": "TIC101"},
    ]
    assert signals == expected


def test_reconcile_legacy_dictionary_signal() -> None:
    assert canonical_role_from_legacy("PV (measured)") == "pv"
    assert canonical_role_from_legacy("SP") == "sp"
    assert canonical_role_from_legacy("OUT (controller output)") == "out"
    assert canonical_role_from_legacy("mode flag") == "mode"
    assert canonical_role_from_legacy("feedback (actuator position)") == "fb"
    assert canonical_role_from_legacy("valve position (AI)") == "fb"
    assert canonical_role_from_legacy("valve reference (AO)") == "fb"
    assert canonical_role_from_legacy("MEAS") == "input"
    assert canonical_role_from_legacy("PV") == "pv"
    assert canonical_role_from_legacy("unknown") is None


def test_loops_from_signals_assembles_analysable_loops() -> None:
    signals = [
        {"tag": "T1.PV", "role": "pv", "loop": "T1"},
        {"tag": "T1.SP", "role": "sp", "loop": "T1"},
        {"tag": "T1.OUT", "role": "out", "loop": "T1"},
        {"tag": "T1.MODE", "role": "mode", "loop": "T1"},
        {"tag": "FEED_RATE", "role": "input"},
    ]
    loops = loops_from_signals(signals)

    assert loops == [
        {"id": "T1", "pv": "T1.PV", "sp": "T1.SP", "out": "T1.OUT", "mode": "T1.MODE"}
    ]


def test_loops_from_signals_skips_incomplete_loops_without_out() -> None:
    signals = [
        {"tag": "T1.PV", "role": "pv", "loop": "T1"},
        {"tag": "T1.SP", "role": "sp", "loop": "T1"},
    ]
    assert loops_from_signals(signals) == []

