"""Tests that OPC UA StatusCodes map to the quality codes Good 0, Uncertain 1, Bad 2."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from crosscut_connectors.opcua_import import _quality_from_status

GOOD_CODE = 0x00000000
UNCERTAIN_CODE = 0x40900000  # UncertainNoCommunicationLastUsableValue
BAD_CODE = 0x80000000  # BadUnexpectedError


@pytest.mark.parametrize(
    ("raw_code", "expected"),
    [(GOOD_CODE, 0), (UNCERTAIN_CODE, 1), (BAD_CODE, 2)],
    ids=["good", "uncertain", "bad"],
)
def test_raw_status_code_maps_to_quality(raw_code: int, expected: int) -> None:
    assert _quality_from_status(raw_code) == expected


@pytest.mark.parametrize(
    ("raw_code", "expected"),
    [(GOOD_CODE, 0), (UNCERTAIN_CODE, 1), (BAD_CODE, 2)],
    ids=["good", "uncertain", "bad"],
)
def test_status_object_with_value_maps_to_quality(raw_code: int, expected: int) -> None:
    status = SimpleNamespace(value=raw_code)
    assert _quality_from_status(status) == expected


@pytest.mark.parametrize(
    ("raw_code", "expected"),
    [(GOOD_CODE, 0), (UNCERTAIN_CODE, 1), (BAD_CODE, 2)],
    ids=["good", "uncertain", "bad"],
)
def test_status_object_with_is_good_maps_to_quality(raw_code: int, expected: int) -> None:
    status = SimpleNamespace(value=raw_code, is_good=lambda: raw_code == GOOD_CODE)
    assert _quality_from_status(status) == expected
