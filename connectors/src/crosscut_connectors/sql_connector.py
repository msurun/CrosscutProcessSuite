"""Relational database SQL connector adapter (Phase 1, #43; historian profiles #50).

Browses relational database tables and schemas, queries column metadata, and reads historical
series through SQL SELECT queries. Live streaming and write methods are strictly excluded.
With ``options["profile"]`` the same adapter reads one vendor historian (IP.21, PHD, InSQL,
WinCC) through the JSON templates in ``sql_profiles/``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from crosscut_connectors.base import (
    CAP_BROWSE,
    CAP_HISTORY,
    CAP_METADATA,
    CAP_READ_LIVE,
    Connector,
    LiveValue,
    NodeInfo,
    NotSupportedError,
    SourceConnectionError,
    TagMetadata,
)
from crosscut_connectors.sql_profiles import (
    HistorianProfile,
    SqlQuery,
    load_profile,
    load_profile_file,
    map_quality,
)


class SqlConnector(Connector):
    """Read-only SQL database connector."""

    def __init__(
        self,
        endpoint: str,
        options: Mapping[str, Any] | None = None,
        connection: Any | None = None,
    ) -> None:
        """Create the adapter; ``connection`` is an optional host-supplied DB-API connection.

        Without a connection the adapter opens sqlite paths from ``endpoint`` itself.
        ``options`` may select a shipped profile (``profile``) or a site profile file
        (``profile_path``), which overrides the shipped name.
        """
        self.endpoint = endpoint
        self.options = dict(options or {})
        self.profile = _load_profile_option(self.options)
        self._connection = connection

    def capabilities(self) -> set[str]:
        """Declare supported capabilities; a profile also supplies latest values."""
        if self.profile is not None:
            return {CAP_BROWSE, CAP_METADATA, CAP_HISTORY, CAP_READ_LIVE}
        return {CAP_BROWSE, CAP_METADATA, CAP_HISTORY}

    def browse(self, node_id: str | None = None) -> list[NodeInfo]:
        """List tables or columns in the database, or the profile's historian tags."""
        if self.profile is not None:
            return self._browse_profile_tags(node_id)
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

    def _browse_profile_tags(self, node_id: str | None) -> list[NodeInfo]:
        """List the profile's tags as leaf nodes; they have no children to browse."""
        assert self.profile is not None
        if node_id:
            return []
        rows = self._run(self.profile.browse.sql, ())
        return [_node_from_row(self.profile.browse, row) for row in rows]

    def metadata(self, tag_ids: Sequence[str]) -> list[TagMetadata]:
        """Return metadata for column identifiers or for the profile's tags."""
        if self.profile is None:
            return [TagMetadata(id=tag_id) for tag_id in tag_ids]
        return [self._profile_metadata(tag_id) for tag_id in tag_ids]

    def _profile_metadata(self, tag_id: str) -> TagMetadata:
        """Fetch one tag's description, unit and engineering limits.

        Raises LookupError when the profile's metadata query knows no such tag.
        """
        assert self.profile is not None
        rows = self._run(self.profile.metadata.sql, (tag_id,))
        if not rows:
            raise LookupError(f"profile {self.profile.name!r} has no tag {tag_id!r}")
        return _metadata_from_row(self.profile.metadata.columns, tag_id, rows[0])

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> Mapping[str, Any]:
        """Read historical records using parameterized SELECT queries.

        With a profile the ``data`` list holds one dict per sample with keys ``tag_id``,
        ``timestamp_utc``, ``value`` and ``quality`` (already mapped to 0/1/2), sorted by
        tag and time. ``period_s`` uses the profile's period query when it has one;
        otherwise the caller receives all archive samples and may downsample them.
        """
        if self.profile is not None:
            return self._profile_history(tag_ids, start_utc, end_utc, period_s)
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

    def _profile_history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None,
    ) -> dict[str, Any]:
        """Query every tag, map its quality and return samples in tag/time order."""
        assert self.profile is not None
        samples: list[dict[str, Any]] = []
        for tag_id in tag_ids:
            samples += self._samples_for_tag(tag_id, start_utc, end_utc, period_s)
        samples.sort(key=_sample_order)
        return {"tag_ids": list(tag_ids), "data": samples, "query": self.profile.history.sql}

    def _samples_for_tag(
        self, tag_id: str, start_utc: str, end_utc: str, period_s: float | None
    ) -> list[dict[str, Any]]:
        """Run the history or period query for one tag and build its samples."""
        assert self.profile is not None
        sql, params = _history_statement(self.profile, tag_id, start_utc, end_utc, period_s)
        rows = self._run(sql, params)
        return [_sample_from_row(self.profile, tag_id, row) for row in rows]

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Read the profile's latest archived value per tag.

        Without a profile this adapter has no live source, so the call is unsupported.
        Raises LookupError when a requested tag has no value in the archive.
        """
        if self.profile is None:
            raise NotSupportedError("SQL connector does not support live streaming")
        return {tag_id: self._latest_value(tag_id) for tag_id in tag_ids}

    def _latest_value(self, tag_id: str) -> LiveValue:
        """The newest archive sample for one tag, with mapped quality."""
        assert self.profile is not None
        rows = self._run(self.profile.latest.sql, (tag_id,))
        if not rows:
            raise LookupError(f"profile {self.profile.name!r} has no latest value for {tag_id!r}")
        return _live_value_from_row(self.profile, rows[0])

    @contextmanager
    def _session(self) -> Iterator[Any]:
        """Yield the host-supplied connection, or open the endpoint as an sqlite file."""
        if self._connection is not None:
            yield self._connection
            return
        with closing(sqlite3.connect(_sqlite_path(self.endpoint))) as connection:
            yield connection

    def _run(self, sql: str, params: Sequence[Any]) -> list[Sequence[Any]]:
        """Run one profile SELECT with bound parameters and return its rows."""
        with self._session() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, tuple(params))
                return cursor.fetchall()
            finally:
                cursor.close()


def _load_profile_option(options: Mapping[str, Any]) -> HistorianProfile | None:
    """The profile chosen by ``options``; ``profile_path`` overrides a shipped name."""
    profile_path = options.get("profile_path")
    if profile_path:
        return load_profile_file(Path(str(profile_path)))
    profile_name = options.get("profile")
    return load_profile(str(profile_name)) if profile_name else None


def _sqlite_path(endpoint: str) -> str:
    """File path of a ``sqlite:///`` endpoint, or ``:memory:`` for an empty path."""
    if not endpoint.startswith("sqlite:"):
        raise SourceConnectionError(
            "SQL historian profiles need a sqlite endpoint or a host-supplied DB-API "
            f"connection, got {endpoint!r}"
        )
    path = endpoint.replace("sqlite:///", "").replace("sqlite://", "")
    return path or ":memory:"


def _history_statement(
    profile: HistorianProfile,
    tag_id: str,
    start_utc: str,
    end_utc: str,
    period_s: float | None,
) -> tuple[str, tuple[Any, ...]]:
    """SQL and bound values for one tag; a period request uses the period query."""
    if period_s is not None and profile.history.period_sql:
        sql = profile.history.period_sql
        return sql, (tag_id, start_utc, end_utc, period_s)
    return profile.history.sql, (tag_id, start_utc, end_utc)


def _node_from_row(query: SqlQuery, row: Sequence[Any]) -> NodeInfo:
    """Build a browse node from one tag row; description and unit are optional."""
    tag = str(row[query.columns["tag"]])
    return NodeInfo(
        id=tag,
        name=tag,
        node_type="variable",
        has_children=False,
        data_type=_text_or_none(row, query.columns.get("data_type")),
        unit=_text_or_none(row, query.columns.get("unit")),
        description=_text_or_none(row, query.columns.get("description")),
    )


def _metadata_from_row(
    columns: Mapping[str, int], tag_id: str, row: Sequence[Any]
) -> TagMetadata:
    """Build tag metadata from one profile row; every field but the id is optional."""
    return TagMetadata(
        id=tag_id,
        unit=_text_or_none(row, columns.get("unit")),
        description=_text_or_none(row, columns.get("description")),
        eng_min=_float_or_none(row, columns.get("eng_min")),
        eng_max=_float_or_none(row, columns.get("eng_max")),
    )


def _sample_from_row(
    profile: HistorianProfile, tag_id: str, row: Sequence[Any]
) -> dict[str, Any]:
    """One history sample with the profile's quality code mapped to 0/1/2."""
    columns = profile.history.columns
    return {
        "tag_id": tag_id,
        "timestamp_utc": _utc_text(row[columns["timestamp"]]),
        "value": _float_or_none(row, columns["value"]),
        "quality": map_quality(profile.quality, row[columns["quality"]]),
    }


def _live_value_from_row(profile: HistorianProfile, row: Sequence[Any]) -> LiveValue:
    """Build one LiveValue from a latest-value row, mapping the vendor quality code."""
    columns = profile.latest.columns
    return LiveValue(
        value=_float_or_none(row, columns["value"]),
        quality=map_quality(profile.quality, row[columns["quality"]]),
        timestamp_utc=_utc_text(row[columns["timestamp"]]),
    )


def _sample_order(sample: Mapping[str, Any]) -> tuple[str, str]:
    """Sort samples by tag, then ISO timestamp (UTC ISO text sorts chronologically)."""
    return str(sample["tag_id"]), str(sample["timestamp_utc"])


def _text_or_none(row: Sequence[Any], index: int | None) -> str | None:
    """The row value at ``index`` as text, or None when the column is absent or NULL."""
    if index is None or row[index] is None:
        return None
    return str(row[index])


def _float_or_none(row: Sequence[Any], index: int | None) -> float | None:
    """The row value at ``index`` as a float, or None when the column is absent or NULL."""
    if index is None or row[index] is None:
        return None
    return float(row[index])


def _utc_text(value: Any) -> str:
    """Render a driver timestamp as ISO-8601 text; UTC offsets become a trailing Z."""
    if hasattr(value, "isoformat"):
        return str(value.isoformat()).replace("+00:00", "Z")
    return str(value)
