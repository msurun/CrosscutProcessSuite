# runtime/src/crosscut_runtime/addressing.py
# Translates site tag ids to the addresses a connector reads (e.g. OPC UA node ids) and back.
# Tags without an address keep their id, so a connector sees the same ids as before.
"""Connector wrapper that reads each site tag at its configured address."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class AddressedConnector:
    """Wraps a connector so that read_live is called with addresses, not tag ids."""

    def __init__(self, inner: Any, addresses: dict[str, str]) -> None:
        """Keep the wrapped connector and the tag id to address map."""
        self._inner = inner
        self._addresses = addresses

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, Any]:
        """Read the addresses of the given tags; the result is keyed by the original tag ids."""
        pairs = [(self._addresses.get(tag, tag), tag) for tag in tag_ids]
        answer = self._inner.read_live([address for address, _ in pairs])
        return {tag: answer[address] for address, tag in pairs if address in answer}

    def __getattr__(self, name: str) -> Any:
        """Delegate every other method or attribute to the wrapped connector."""
        return getattr(self._inner, name)
