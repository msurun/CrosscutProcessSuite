# connectors/src/crosscut_connectors/import_target.py
"""Where an importer writes its dataset and how it reads naive timestamps.

Groups the options every importer shares so that import functions stay within
the four-parameter limit and callers pass one value instead of three.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportTarget:
    """Destination of an import.

    Attributes
    ----------
    out_dir: Path
        Directory the dataset is written to.
    dataset_id: str
        Identifier stored in the dataset metadata.
    tz: str
        IANA timezone name (e.g. ``"Europe/Warsaw"``) used for timestamps that
        carry no UTC offset.
    """

    out_dir: Path
    dataset_id: str
    tz: str = "UTC"
