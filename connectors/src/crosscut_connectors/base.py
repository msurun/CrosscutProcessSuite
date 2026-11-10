"""Unified read connector interface and value models (Phase 1, #43).

Defines the read-only Protocol for plant data sources (OPC UA, SQL, CSV/historian) along with
standard node metadata and live value representations. Writes are strictly forbidden (ADR 012).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

CAP_BROWSE = "browse"
CAP_METADATA = "metadata"
CAP_HISTORY = "history"
CAP_READ_LIVE = "read_live"
CAP_SUBSCRIBE = "subscribe"


class ConnectorError(Exception):
    """Base exception for all connector operation failures."""


class NotSupportedError(ConnectorError):
    """Raised when an adapter does not support an optional capability."""


class SourceConnectionError(ConnectorError):
    """Raised when a connector fails to establish or maintain a connection."""


@dataclass(frozen=True)
class NodeInfo:
    """Representation of an address space node during hierarchy browsing."""

    id: str
    name: str
    node_type: str  # e.g., "folder", "variable", "object"
    has_children: bool
    data_type: str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class TagMetadata:
    """Engineering and descriptive attributes associated with a signal tag."""

    id: str
    unit: str | None = None
    description: str | None = None
    eng_min: float | None = None
    eng_max: float | None = None


@dataclass(frozen=True)
class LiveValue:
    """A sampled value with its quality code and timestamp."""

    value: float | None
    quality: int  # 0 good, 1 uncertain, 2 bad
    timestamp_utc: str


@dataclass(frozen=True)
class Snapshot:
    """All requested tags sampled together for one control cycle.

    ``comm_ok`` is False when the source could not be read at all; every value then has quality
    2 and ``reason`` says why (``"comm_loss"``).
    """

    cycle_utc: str
    values: dict[str, LiveValue]
    comm_ok: bool
    reason: str | None = None


@runtime_checkable
class SnapshotConnector(Protocol):
    """Optional extension: connectors that can sample one consistent cycle snapshot."""

    def read_snapshot(self, tag_ids: Sequence[str]) -> Snapshot:
        """Sample all tags in one batch; never raises on communication loss."""
        ...


@runtime_checkable
class Connector(Protocol):
    """Unified read-only protocol for plant and historian data sources.

    # In plain words:
    Exposes read operations across diverse protocols without ever granting write access.
    Writing to control actuators is strictly isolated to the Write Gateway.
    """

    def capabilities(self) -> set[str]:
        """Return the set of operations supported by this connector instance."""
        ...

    def browse(self, node_id: str | None = None) -> list[NodeInfo]:
        """List child nodes at the root or under the given node identifier."""
        ...

    def metadata(self, tag_ids: Sequence[str]) -> list[TagMetadata]:
        """Fetch engineering units, descriptions, and limits for the given tags."""
        ...

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> Mapping[str, Any]:
        """Read historical time-series data for the given tags."""
        ...

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Sample current values, quality codes, and timestamps for the given tags."""
        ...
