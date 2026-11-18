"""CLI for the validation report generator (issue #40): analyser against lab, frozen template.

Reads the time zone and missing codes of the site file (connectors `read_import_settings`)
when the config names a `site_root`, then runs crosscut_softsensor.validation_report.
Usage: python tools/validation_report.py DATA.csv CONFIG.json OUT_DIR
Writes OUT_DIR/report.md and OUT_DIR/report.json; the same input gives the same bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from crosscut_connectors import site
from crosscut_softsensor.alignment import AlignmentError
from crosscut_softsensor.long_format import LabReadSettings, LongFormatError
from crosscut_softsensor.validation_report import ReportError, compute_report, write_report


def site_settings(site_root: str | Path | None) -> LabReadSettings | None:
    """Time zone and missing codes from the site file; None when no site root is given."""
    if site_root is None:
        return None
    declared = site.read_import_settings(site.load_site(Path(site_root)))
    return LabReadSettings(
        timezone=declared.timezone,
        missing_codes=declared.missing_codes,
        missing_text_codes=declared.missing_text_codes,
        codes_by_tag={tag: item.missing_codes for tag, item in declared.tags.items()
                      if item.missing_codes},
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the generator; return 0, or 2 after printing a data, config or site-file error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("out_dir", type=Path)
    arguments = parser.parse_args(argv)
    try:
        document = json.loads(arguments.config.read_text(encoding="utf-8"))
        settings = site_settings(document.get("site_root"))
        report = compute_report(arguments.data, document, settings)
    except (ReportError, AlignmentError, LongFormatError, site.SiteError, OSError,
            ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for path in write_report(report, arguments.out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
