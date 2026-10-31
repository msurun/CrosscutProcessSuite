"""CSV and tabular filesystem connector adapter (Phase 1, #43).

Browses local CSV and Parquet files, extracts column metadata, and reads historical
time-series records. Live streaming and write methods are strictly excluded.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
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


class CsvConnector(Connector):
    """File-based read connector for local directories of tabular files."""

    def __init__(self, endpoint: str, options: Mapping[str, Any] | None = None) -> None:
        self.folder = Path(endpoint)
        self.options = dict(options or {})

    def capabilities(self) -> set[str]:
        """Declare supported read capabilities."""
        return {CAP_BROWSE, CAP_METADATA, CAP_HISTORY}

    def browse(self, node_id: str | None = None) -> list[NodeInfo]:
        """Browse directory files or columns inside a specific file."""
        if not node_id:
            return self._browse_files()
        return self._browse_columns(node_id)

    def _browse_files(self) -> list[NodeInfo]:
        """List CSV and Parquet files in the configured folder."""
        if not self.folder.is_dir():
            return []
        nodes: list[NodeInfo] = []
        for path in sorted(self.folder.glob("*.*")):
            if path.suffix.lower() in (".csv", ".parquet"):
                info = NodeInfo(id=path.name, name=path.name, node_type="file", has_children=True)
                nodes.append(info)
        return nodes

    def _browse_columns(self, file_name: str) -> list[NodeInfo]:
        """List column variable nodes for a file."""
        path = self.folder / file_name
        if not path.is_file():
            return []
        cols = _read_header_columns(path)
        return [
            NodeInfo(id=f"{file_name}/{col}", name=col, node_type="variable", has_children=False)
            for col in cols
        ]

    def metadata(self, tag_ids: Sequence[str]) -> list[TagMetadata]:
        """Return TagMetadata records for requested column identifiers."""
        return [TagMetadata(id=tag_id) for tag_id in tag_ids]

    def history(
        self,
        tag_ids: Sequence[str],
        start_utc: str,
        end_utc: str,
        period_s: float | None = None,
    ) -> Mapping[str, Any]:
        """Read historical tabular data matching requested tags."""
        rows: list[dict[str, Any]] = []
        for tag in tag_ids:
            if "/" not in tag:
                continue
            fname, _col = tag.split("/", 1)
            fpath = self.folder / fname
            if fpath.is_file() and fpath.suffix.lower() == ".csv":
                with open(fpath, encoding="utf-8") as f:
                    rows.extend(csv.DictReader(f))
        return {"tag_ids": list(tag_ids), "data": rows}

    def read_live(self, tag_ids: Sequence[str]) -> dict[str, LiveValue]:
        """Live sampling is not supported by static file directories."""
        raise NotSupportedError("CSV connector does not support live streaming")


def _read_header_columns(path: Path) -> list[str]:
    """Extract column headers from the first line of a CSV or Parquet file."""
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        return pq.read_schema(path).names
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        return next(reader, [])
