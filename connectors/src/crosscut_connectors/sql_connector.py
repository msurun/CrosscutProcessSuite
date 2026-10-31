"""Relational database SQL connector adapter (Phase 1, #43).

Browses relational database tables and schemas, queries column metadata, and reads historical
series through SQL SELECT queries. Live streaming and write methods are strictly excluded.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from crosscut_connectors.base import (
    CAP_BROWSE,
    CAP_HISTORY,
    CAP_METADATA,
    Connector,
    LiveValue,
    NodeInfo,
    NotSupportedError,
    TagMetadata,
)


class SqlConnector(Connector):
    """Read-only SQL database connector."""

    def __init__(self, endpoint: str, options: Mapping[str, Any] | None = None) -> None:
        self.endpoint = endpoint
        self.options = dict(options or {})

    def capabilities(self) -> set[str]:
        """Declare supported capabilities."""
        return {CAP_BROWSE, CAP_METADATA, CAP_HISTORY}

    def browse(self, node_id: str | None = None) -> list[NodeInfo]:
        """List tables or columns in the database."""
        if not node_id:
            return self._browse_tables()
        return self._browse_columns(node_id)

    def _browse_tables(self) -> list[NodeInfo]:
        """List tables in an SQLite connection."""
        if not self.endpoint.startswith("sqlite:"):
            info = NodeInfo(id="default", name="default", node_type="table", has_children=True)
            return [info]
        db_path = self.endpoint.replace("sqlite:///", "").replace("sqlite://", "")
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
        return [NodeInfo(id=t, name=t, node_type="table", has_children=True) for t in tables]

    def _browse_columns(self, table_name: str) -> list[NodeInfo]:
        """List column variable nodes for a table."""
        if not self.endpoint.startswith("sqlite:"):
            return []
        db_path = self.endpoint.replace("sqlite:///", "").replace("sqlite://", "")
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
        return [
            NodeInfo(id=f"{table_name}.{col}", name=col, node_type="variable", has_children=False)
            for col in columns
        ]

    def metadata(self, tag_ids: Sequence[str]) -> list[TagMetadata]:
        """Return metadata for column identifiers."""
        return [TagMetadata(id=tag_id) for tag_id in tag_ids]

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> Mapping[str, Any]:
        """Read historical records using parameterized SELECT queries."""
        if not self.endpoint.startswith("sqlite:"):
            return {"tag_ids": list(tag_ids), "data": [], "query": ""}
        db_path = self.endpoint.replace("sqlite:///", "").replace("sqlite://", "")
        table = self.options.get("table", "history")
        time_col = self.options.get("timestamp_column", "timestamp")
        cols = ", ".join(t.split(".")[-1] for t in tag_ids) if tag_ids else "*"
        query = f"SELECT {time_col}, {cols} FROM {table} WHERE {time_col} >= ? AND {time_col} <= ?"
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (start_utc, end_utc))
            rows = cursor.fetchall()
        return {"tag_ids": list(tag_ids), "data": rows, "query": query}

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Live streaming is not supported on batch SQL connectors."""
        raise NotSupportedError("SQL connector does not support live streaming")
