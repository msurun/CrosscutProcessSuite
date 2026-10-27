"""Cut one tag out of a long-format historian CSV and write a lab-upload CSV.

Interim tool from the plant-1 validation work; to be absorbed into the generic
virtual-sensor engine in Phase 4 of docs/PRODUCT.md.

The soft sensor lab upload expects a two-column file (`sample_time,value`). The historian
exports one row per result, so this tool filters a single tag, optionally shifts its stamps
and drops sentinel values, then writes the upload file.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import math
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from crosscut_softsensor.long_format import TagSeries, load_long_csv

SECONDS_PER_HOUR = 3600.0
OUTPUT_HEADER = ("sample_time", "value")
ISO_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
EXIT_UNKNOWN_TAG = 2
MAX_SUGGESTIONS = 5
# Number of tag names to show in the help and error messages; long lists are unreadable.
MIN_PREVIEW_TAGS = 5


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser with the extractor's options."""
    parser = argparse.ArgumentParser(
        description="Cut one tag from a long-format CSV into a lab-upload CSV.",
    )
    parser.add_argument("--csv", type=Path, required=True, help="long-format input CSV")
    parser.add_argument("--list", action="store_true", help="list tags and exit")
    parser.add_argument("--tag", help="tag name to extract")
    parser.add_argument("--out", type=Path, help="output CSV path (default stdout)")
    parser.add_argument(
        "--utc-offset-h",
        type=float,
        default=0.0,
        help="local offset east of UTC in hours (default 0)",
    )
    parser.add_argument(
        "--shift-h",
        type=float,
        default=0.0,
        help="hours added to every stamp, composite end -> sample time",
    )
    parser.add_argument(
        "--min-valid",
        type=float,
        default=-math.inf,
        help="drop values below this floor, e.g. 0 for analyser concentrations",
    )
    parser.add_argument(
        "--iso",
        action="store_true",
        help="write sample_time as ISO 8601 text (the default; kept for explicitness)",
    )
    return parser


def describe_series(series: TagSeries) -> str:
    """Return one aligned text line with the tag name, count, stamp range and mean."""
    if len(series.t_s) == 0:
        return f"{series.tag:<40} n=0"
    first_time = format_iso_utc(series.t_s[0])
    last_time = format_iso_utc(series.t_s[-1])
    mean_value = float(np.nanmean(series.values))
    return (
        f"{series.tag:<40} n={len(series.t_s):<6} "
        f"first={first_time} last={last_time} mean={mean_value:.6g}"
    )


def format_iso_utc(t_s: float) -> str:
    """Format seconds since the Unix epoch as ISO 8601 UTC text."""
    return datetime.fromtimestamp(t_s, tz=UTC).strftime(ISO_UTC_FORMAT)


def select_series(by_tag: dict[str, TagSeries], tag: str) -> TagSeries:
    """Return the series for `tag`, raising `KeyError` with close-match suggestions if absent."""
    if tag in by_tag:
        return by_tag[tag]
    suggestions = difflib.get_close_matches(tag, list(by_tag), n=MAX_SUGGESTIONS)
    if suggestions:
        hint = "Unknown tag '" + tag + "'. Closest names: " + ", ".join(suggestions)
    else:
        hint = f"Unknown tag '{tag}'. The file has no similar tag names."
    raise KeyError(hint)


def filter_and_shift(series: TagSeries, shift_h: float, min_valid: float) -> TagSeries:
    """Shift stamps by `shift_h` hours and drop samples with a value below `min_valid`."""
    shifted_s = series.t_s + shift_h * SECONDS_PER_HOUR
    keep = series.values >= min_valid
    return TagSeries(tag=series.tag, t_s=shifted_s[keep], values=series.values[keep])


def write_upload_csv(handle, series: TagSeries) -> None:
    """Write `sample_time,value` rows (ISO UTC stamps, full float precision) to `handle`."""
    writer = csv.writer(handle)
    writer.writerow(OUTPUT_HEADER)
    for t_s, value in zip(series.t_s, series.values, strict=True):
        writer.writerow((format_iso_utc(t_s), repr(float(value))))


def run_list(by_tag: dict[str, TagSeries]) -> int:
    """Print the tag inventory to stdout in name order and return the exit code."""
    sample_tag = next(iter(by_tag), None)
    if sample_tag is None:
        print("(no tags found)", file=sys.stderr)
        return 1
    del sample_tag  # The variable only documents the empty-file case above.
    for tag in sorted(by_tag):
        print(describe_series(by_tag[tag]))
    return 0


def run_extract(args: argparse.Namespace, by_tag: dict[str, TagSeries]) -> int:
    """Extract the requested tag and write the upload CSV, returning the exit code."""
    if args.tag is None:
        print("--tag is required unless --list is given", file=sys.stderr)
        return EXIT_UNKNOWN_TAG
    try:
        series = select_series(by_tag, args.tag)
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return EXIT_UNKNOWN_TAG
    processed = filter_and_shift(series, args.shift_h, args.min_valid)
    _write_output(processed, args.out)
    return 0


def _write_output(series: TagSeries, out_path: Path | None) -> None:
    """Write the upload CSV to `out_path`, or to stdout when it is None."""
    if out_path is None:
        write_upload_csv(sys.stdout, series)
        return
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        write_upload_csv(handle, series)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line tool and return the process exit code."""
    args = build_parser().parse_args(argv)
    by_tag = load_long_csv(args.csv, utc_offset_h=args.utc_offset_h)
    if args.list:
        return run_list(by_tag)
    return run_extract(args, by_tag)


if __name__ == "__main__":
    raise SystemExit(main())
