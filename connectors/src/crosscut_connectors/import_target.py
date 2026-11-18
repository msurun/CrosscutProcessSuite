# connectors/src/crosscut_connectors/import_target.py
"""Where an importer writes its dataset and how it reads naive timestamps.

Groups the options every importer shares so that import functions stay within
the four-parameter limit and callers pass one value instead of three.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from crosscut_connectors.site import SiteImportSettings, TagSettings


@dataclass(frozen=True)
class ImportTarget:
    """Destination of an import and the site settings that apply to it.

    Attributes
    ----------
    out_dir: Path
        Directory the dataset is written to.
    dataset_id: str
        Identifier stored in the dataset metadata.
    tz: str
        IANA timezone name (e.g. ``"Europe/Warsaw"``) used for timestamps that
        carry no UTC offset. It beats the site time zone when set explicitly.
    settings: SiteImportSettings | None
        The site settings read through ``site.read_import_settings``; None keeps
        the documented neutral defaults (UTC, no missing codes, no conversions).
    source_id: str | None
        Id of the ``sources`` entry being imported, when the caller knows it; it
        selects the per-source missing codes for tags the catalogue does not name.
    """

    out_dir: Path
    dataset_id: str
    tz: str = "UTC"
    settings: SiteImportSettings | None = None
    source_id: str | None = None

    def settings_for(self, tag_id: str | None) -> TagSettings:
        """Effective site settings of one imported tag (neutral when no site file was read)."""
        if self.settings is None:
            return SiteImportSettings().for_tag(None)
        if tag_id in self.settings.tags or self.source_id is None:
            return self.settings.for_tag(tag_id)
        return self.settings.for_source(self.source_id)

