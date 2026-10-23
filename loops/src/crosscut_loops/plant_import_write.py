"""Write a whole PI wide-file import as a Crosscut dataset.

Takes the in-memory plant table (original sample times, one column per tag) and writes
`tags.json`, the long Parquet data, `project.json` and `test_windows.json`. No resampling:
a gap between test windows stays a gap, and a missing cell becomes NaN with a bad quality.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from crosscut_sim.dataset import DatasetInfo, Samples, write_dataset

from crosscut_loops.plant_import import (
    PlantTable,
    find_gaps,
    iso_utc,
    read_plant_table,
    test_windows,
)
from crosscut_loops.plant_import_loops import (
    DetectedLoop,
    DictRow,
    detect_loops,
    read_dictionary,
)
from crosscut_loops.plant_import_time import TimeZoneSpec
from crosscut_loops.step_test_io import Note

# Quality codes of a stored sample (same convention as crosscut_sim.dataset.Samples).
GOOD_QUALITY = 0
BAD_QUALITY = 2

SCOPE_LOOPS = "loops"
SCOPE_PROCESS = "process"
VALID_SCOPES = frozenset({SCOPE_LOOPS, SCOPE_PROCESS})

# A process tag must be present in at least half of the rows to be worth storing.
MIN_PRESENT_FRACTION = 0.5
# Upper bound on written tags, so the long table stays a manageable size in memory.
MAX_PROCESS_TAGS = 500

# Role names in tags.json for the loop signals; anything else is 'other'.
LOOP_ROLES = (("pv", "PV"), ("sp", "SP"), ("out", "OUT"), ("mode", "MODE"))
OTHER_ROLE = "other"

# tag ids must match the tags schema: letters, digits and _ . : -
TAG_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
INVALID_TAG_ID_CHARS = re.compile(r"[^A-Za-z0-9_.:-]")


@dataclass(frozen=True)
class PlantImportResult:
    """What the import wrote: notes, detected loops, tag counts and test windows."""

    notes: list[Note]
    loops: list[DetectedLoop]
    tags_written: int
    tags_skipped: int
    windows: list[dict]


def select_tags(
    table: PlantTable, loops: list[DetectedLoop], scope: str
) -> tuple[list[str], int]:
    """Choose the tag columns to write, in file order.

    Returns the tag ids to write and the number of columns skipped. Scope 'loops'
    keeps only the signals of complete loops; scope 'process' also keeps any other
    column that is at least half present and not constant, up to MAX_PROCESS_TAGS.

    Raises:
        ValueError: when scope is neither 'loops' nor 'process'.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"unknown scope {scope!r}; use {SCOPE_LOOPS!r} or {SCOPE_PROCESS!r}")
    wanted = _loop_signals(loops)
    # Loop tags are always kept, so they are not candidates for the process budget.
    kept = [column for column in table.columns if column in wanted]
    if scope == SCOPE_LOOPS:
        return kept, len(table.columns) - len(kept)
    extras = _process_candidates(table, wanted)
    room = MAX_PROCESS_TAGS - len(kept)
    return kept + extras[:room], len(table.columns) - len(kept) - min(len(extras), room)


def _loop_signals(loops: list[DetectedLoop]) -> set[str]:
    """Return every tag name used as a signal of a complete loop."""
    signals: set[str] = set()
    for loop in loops:
        if not loop.complete:
            continue
        signals.update(tag for tag in (loop.pv, loop.sp, loop.out, loop.mode) if tag)
        signals.update(loop.valves)
        if loop.feedback:
            signals.add(loop.feedback)
    return signals


def _process_candidates(table: PlantTable, wanted: set[str]) -> list[str]:
    """Return other columns, in file order, that are mostly present and not constant."""
    candidates: list[str] = []
    for column in table.columns:
        if column not in wanted and _is_useful_process_tag(table.columns[column]):
            candidates.append(column)
    return candidates


def _is_useful_process_tag(values: np.ndarray) -> bool:
    """True when at least half the cells are finite and the finite values vary."""
    finite = values[np.isfinite(values)]
    if finite.size < MIN_PRESENT_FRACTION * values.size:
        return False
    return float(np.max(finite)) != float(np.min(finite))


def tag_rows(
    ids: list[str], loops: list[DetectedLoop], dictionary: list[DictRow] | None
) -> list[dict]:
    """Build the tags.json rows for the written tag ids.

    Description and unit come from the dictionary when given. The role is PV, SP,
    OUT or MODE for a complete loop's signals, else 'other'. A tag id with a
    character the schema forbids is sanitised with '_'; the original column name
    is then kept in 'name' and in the source address.
    """
    role_by_tag = _role_by_tag(loops)
    rows_by_tag = {row.tag: row for row in dictionary} if dictionary else {}
    return [_tag_row(tag, role_by_tag, rows_by_tag) for tag in ids]


def _role_by_tag(loops: list[DetectedLoop]) -> dict[str, str]:
    """Map each loop signal tag to its tags.json role."""
    roles: dict[str, str] = {}
    for loop in loops:
        if not loop.complete:
            continue
        for field_name, role in LOOP_ROLES:
            tag = getattr(loop, field_name)
            if tag:
                roles[tag] = role
    return roles


def _tag_row(tag: str, role_by_tag: dict[str, str], rows_by_tag: dict[str, DictRow]) -> dict:
    """One tags.json row for a written tag."""
    entry = rows_by_tag.get(tag)
    return {
        "id": _tag_id(tag),
        "name": tag,
        "description": entry.description if entry else "",
        "unit": entry.unit if entry else "",
        "type": "float",
        "role": role_by_tag.get(tag, OTHER_ROLE),
        "source": {"driver": "csv", "address": tag},
    }


def _tag_id(tag: str) -> str:
    """Return the tag id, replacing characters the tags schema forbids with '_'."""
    return tag if TAG_ID_PATTERN.match(tag) else INVALID_TAG_ID_CHARS.sub("_", tag)


def import_plant(
    path: Path,
    dictionary_text: str | None,
    out_dir: Path,
    tz: TimeZoneSpec,
    scope: str = SCOPE_PROCESS,
) -> PlantImportResult:
    """Write the whole PI file at ``path`` as a dataset in ``out_dir``.

    Keeps the original timestamps (no resampling): values are float64, a missing cell
    is stored as NaN with quality 2, and a MODE tag is forward-filled (a leading gap
    becomes 0, manual). Writes project.json and test_windows.json next to the dataset.

    Raises:
        FileExistsError: when ``out_dir`` exists and is not empty.
        ValueError: for an unknown scope or an unreadable dictionary.
    """
    _refuse_non_empty(out_dir)
    try:
        result = _write_import(path, dictionary_text, out_dir, tz, scope)
    except BaseException:
        # A half-written dataset would look valid to the web app, so remove it.
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return result


def _refuse_non_empty(out_dir: Path) -> None:
    """Raise FileExistsError if ``out_dir`` already holds files."""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"{out_dir} already exists; choose a new dataset directory")


def _write_import(
    path: Path,
    dictionary_text: str | None,
    out_dir: Path,
    tz: TimeZoneSpec,
    scope: str,
) -> PlantImportResult:
    """Read, select, write the dataset and its sidecar files; return the result."""
    table = read_plant_table(path, tz)
    dictionary = read_dictionary(dictionary_text) if dictionary_text else None
    loops = detect_loops(list(table.columns), dictionary)
    ids, skipped = select_tags(table, loops, scope)
    samples, mode_gap = _build_samples(table, ids)
    # Data, tags.json and project.json must use the same (schema-safe) ids, e.g. "#" becomes "_".
    samples = dataclasses.replace(samples, tag_ids=[_tag_id(i) for i in ids])
    rows = tag_rows(ids, loops, dictionary)
    tags_document = {"schema_version": "0.1.0", "tags": rows}
    start_utc = iso_utc(int(table.ts_ns[0]))
    info = DatasetInfo(out_dir.name, {"kind": "file"}, start_utc, tags_document)
    write_dataset(out_dir, samples, info)
    windows = test_windows(table.ts_ns, table.test)
    _write_project(out_dir, loops, ids)
    _write_windows(out_dir, windows)
    notes = _import_notes(table, scope, len(ids), skipped, mode_gap)
    return PlantImportResult(notes, loops, len(ids), skipped, windows)


def _build_samples(table: PlantTable, ids: list[str]) -> tuple[Samples, bool]:
    """Build wide Samples for ``ids``; also report whether a MODE leading gap was filled."""
    values = np.column_stack([table.columns[tag] for tag in ids]).astype(np.float64)
    qualities = np.where(np.isfinite(values), GOOD_QUALITY, BAD_QUALITY).astype(np.uint8)
    mode_gap = _forward_fill_mode(table.columns, ids, values)
    return Samples(table.ts_ns, ids, values, qualities), mode_gap


def _forward_fill_mode(
    columns: dict[str, np.ndarray], ids: list[str], values: np.ndarray
) -> bool:
    """Forward-fill the NaN cells of every MODE column in ``values`` (mutates it).

    MODE is 1 = automatic, 0 = manual; a missing reading means "unchanged". A leading
    gap has nothing to hold, so it becomes 0 (manual). Returns True when any leading
    gap was filled that way.
    """
    had_leading_gap = False
    for column_index, tag in enumerate(ids):
        if _is_mode_tag(tag):
            had_leading_gap |= _fill_one_mode_column(values[:, column_index])
    return had_leading_gap


def _is_mode_tag(tag: str) -> bool:
    """True for a controller mode flag ('<prefix>-<number>.auto#state')."""
    return tag.endswith(".auto#state") and ":io.setauto#state" not in tag


def _fill_one_mode_column(signal: np.ndarray) -> bool:
    """Forward-fill one MODE column in place; returns True if a leading gap was set to 0."""
    missing = ~np.isfinite(signal)
    if not missing.any():
        return False
    # Index of the last present cell at or before each row: -1 means none seen yet.
    last_present = np.maximum.accumulate(np.where(missing, -1, np.arange(signal.size)))
    had_leading_gap = bool((last_present < 0).any())
    # np.where picks the carried value, else 0.0 for the leading gap, for the NaN cells.
    signal[missing] = np.where(
        last_present[missing] >= 0, signal[np.maximum(last_present[missing], 0)], 0.0
    )
    return had_leading_gap


def _write_project(out_dir: Path, loops: list[DetectedLoop], ids: list[str]) -> None:
    """Write project.json: one entry per complete loop, tag ids as written."""
    written = set(ids)
    entries = [_project_entry(loop) for loop in loops if _is_written_loop(loop, written)]
    (out_dir / "project.json").write_text(
        json.dumps({"loops": entries}, indent=2) + "\n", encoding="utf-8"
    )


def _is_written_loop(loop: DetectedLoop, written: set[str]) -> bool:
    """True when the loop is complete and all its main signals were written."""
    return loop.complete and all(
        getattr(loop, field_name) in written for field_name, _ in LOOP_ROLES
    )


def _project_entry(loop: DetectedLoop) -> dict[str, object]:
    """One project.json loop entry (the four main signals are never None)."""
    return {
        "id": loop.id,
        "name": loop.name,
        "pv": _tag_id(str(loop.pv)),
        "sp": _tag_id(str(loop.sp)),
        "out": _tag_id(str(loop.out)),
        "mode": _tag_id(str(loop.mode)),
        "unit": loop.unit,
        "process_kind": loop.process_kind,
        "cell": loop.cell,
    }


def _write_windows(out_dir: Path, windows: list[dict]) -> None:
    """Write test_windows.json: the contiguous runs of the `test` column."""
    (out_dir / "test_windows.json").write_text(
        json.dumps(windows, indent=2) + "\n", encoding="utf-8"
    )


def _import_notes(
    table: PlantTable, scope: str, written: int, skipped: int, mode_gap: bool
) -> list[Note]:
    """Notes about what the import assumed: timing, scope, gaps and the MODE fill."""
    median_period_s, gap_count, _ = find_gaps(table.ts_ns)
    notes = list(table.notes)
    notes.append(
        Note(
            "import_scope",
            f"scope '{scope}': {written} tags written, {skipped} columns skipped",
            {"scope": scope, "written": written, "skipped": skipped},
        )
    )
    notes.append(
        Note(
            "gaps",
            f"{gap_count} gaps longer than 5 sampling periods "
            f"(median period {median_period_s:g} s)",
            {"count": gap_count, "median_period_s": median_period_s},
        )
    )
    if mode_gap:
        notes.append(
            Note("mode_leading_gap", "a MODE column started empty: set to 0 (manual)")
        )
    return notes
