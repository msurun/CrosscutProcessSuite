# runtime/tests/test_addressed_connector.py
# Checks that AddressedConnector reads tags at their addresses and keys results by tag id.
"""Tests for the tag id to address translation in front of a connector."""

from __future__ import annotations

from collections.abc import Sequence

from crosscut_connectors.base import LiveValue
from crosscut_runtime.addressing import AddressedConnector

PV_ADDRESS = "nsu=urn:crosscut:sim;s=sim.wb.top_comp"


class RecordingConnector:
    """A fake connector that records the addresses it is asked for and echoes their length."""

    def __init__(self) -> None:
        """Start with no reads recorded."""
        self.asked: list[list[str]] = []

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Record the request and answer each address with its length as the value."""
        self.asked.append(list(tag_ids))
        stamp = "2026-01-01T00:00:00+00:00"
        return {a: LiveValue(value=float(len(a)), quality=0, timestamp_utc=stamp) for a in tag_ids}


def test_tags_are_read_at_their_addresses_and_keyed_by_tag() -> None:
    inner = RecordingConnector()
    wrapped = AddressedConnector(inner, {"FIC101.pv": PV_ADDRESS})
    result = wrapped.read_live(["FIC101.pv", "FIC101.sp"])
    assert inner.asked == [[PV_ADDRESS, "FIC101.sp"]]
    assert set(result) == {"FIC101.pv", "FIC101.sp"}
    assert result["FIC101.pv"].value == float(len(PV_ADDRESS))


def test_tag_without_address_is_read_by_its_id() -> None:
    inner = RecordingConnector()
    wrapped = AddressedConnector(inner, {})
    result = wrapped.read_live(["FIC101.out"])
    assert inner.asked == [["FIC101.out"]]
    assert set(result) == {"FIC101.out"}
