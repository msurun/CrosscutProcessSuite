"""Read tolerant CSV sources for the compatibility import entry points.

These reads preserve the original table and row contracts; dataset creation stays with callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def read_csv_import(path: Path, options: Mapping[str, Any]) -> dict[str, Any]:
    """Read a complete wide table or long rows without changing legacy import semantics."""
    if options["import_layout"] == "wide":
        from crosscut_connectors.csv_import import _read_table

        return {"table": _read_table(path)}
    if options["import_layout"] == "long":
        from crosscut_connectors.csv_long import read_long_file

        parsed = read_long_file(path)
        return {"rows": parsed.rows, "units": parsed.units}
    raise ValueError("import_layout must be 'wide' or 'long'")
