"""HTTP routes of the step-test intake: preview a historian CSV, check it, make a dataset of it.

Wraps crosscut_loops.step_test_{io,check,dataset} (the same code as the step_test_cli). The only
write is the NEW dataset folder ``<data root>/<dataset_id>`` made by POST /intake/dataset; preview
and check touch no file, and nothing here reaches a plant. A failed creation removes its folder.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import numpy as np
from crosscut_loops.identification_ipdt import IpdtIdentificationError
from crosscut_loops.overview import LoopTags
from crosscut_loops.step_test_check import StepTestCheck, check_step_test, resample_uniform
from crosscut_loops.step_test_dataset import DatasetSpec, write_step_test_notes
from crosscut_loops.step_test_io import (
    TAG_NAMES,
    TIME_NAMES,
    VALUE_NAMES,
    Note,
    ReadOptions,
    Record,
    detect_decimal,
    read_record_text,
    table_from_text,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

MAX_BODY_BYTES = 25_000_000
PREVIEW_ROWS = 8
PREVIEW_HEAD_CHARS = 200_000
MAX_CHART_POINTS = 800
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
CATEGORY_ORDER = ("time", "sp", "mode", "out", "pv")
CATEGORY_WORDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "time": (("time", "timestamp", "date", "datetime", "t"), ("timestamp",)),
    "sp": (("sp", "setpoint", "set"), ("setp",)),
    "mode": (("mode", "mod", "auto", "man"), ("mode",)),
    "out": (("out", "op", "mv", "valve", "output"), ("out", "valve")),
    "pv": (("pv", "level", "lvl", "lic"), ("lic", "lvl", "level")),
}  # category -> (exact tokens, token prefixes)


class Mapping(BaseModel):
    """Which columns (wide) or tags (long) hold the signals; empty means not given."""

    time_col: str | None = None
    pv_col: str | None = None
    out_col: str | None = None
    sp_col: str | None = None
    mode_col: str | None = None
    tag_pv: str | None = None
    tag_out: str | None = None
    tag_sp: str | None = None
    tag_mode: str | None = None
    tag_col: str | None = None
    value_col: str | None = None
    quality_col: str | None = None


class Options(BaseModel):
    """How to parse the text; 'auto' detects."""

    time_format: Literal["auto", "iso", "seconds"] = "auto"
    decimal: Literal["auto", "comma", "dot"] = "auto"
    delimiter: str = "auto"
    manual_value: float = 0.0


class PreviewRequest(BaseModel):
    """CSV text to look at."""

    csv_text: str


class CheckRequest(PreviewRequest):
    """CSV text, the signal mapping and the parse options."""

    mapping: Mapping
    options: Options = Field(default_factory=Options)


class DatasetRequest(CheckRequest):
    """A check request plus the name and units of the dataset to create."""

    dataset_id: str = Field(pattern=ID_PATTERN)
    loop_name: str = Field(default="LIC1", pattern=ID_PATTERN)
    process_kind: Literal["integrating", "self_regulating"] = "integrating"
    pv_unit: str = Field(default="%", max_length=16)
    out_unit: str = Field(default="%", max_length=16)


def _unprocessable(message: object) -> HTTPException:
    """A 422 with a friendly message."""
    return HTTPException(status_code=422, detail=message)


def _text(request: PreviewRequest) -> str:
    """The CSV text, 413 when it exceeds the body cap."""
    if len(request.csv_text) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="the CSV is larger than 25 MB")
    return request.csv_text


async def _cap_body(request: Request) -> None:
    """Refuse a request whose Content-Length is above the cap before it is parsed (413)."""
    length = request.headers.get("content-length", "0")
    if length.isdigit() and int(length) > MAX_BODY_BYTES + 100_000:
        raise HTTPException(status_code=413, detail="the request is larger than 25 MB")


def _tokens(name: str) -> list[str]:
    """Lower-case alphanumeric tokens of a column or tag name ('LIC1.PV' -> lic1, pv)."""
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def _category(name: str) -> str | None:
    """The signal category a column or tag name suggests, by the fixed priority order."""
    tokens = _tokens(name)
    for cat in CATEGORY_ORDER:
        exact, prefixes = CATEGORY_WORDS[cat]
        if any(t in exact or t.startswith(prefixes) for t in tokens):
            return cat
    return None


def _first_by_category(names: list[str]) -> dict[str, str | None]:
    """The first name of each category (None when no name suggests it)."""
    found: dict[str, str | None] = dict.fromkeys(CATEGORY_ORDER)
    for name in names:
        cat = _category(name)
        if cat and found[cat] is None:
            found[cat] = name
    return found


def _exact(header: list[str], words: tuple[str, ...]) -> str | None:
    """The first header cell that equals one of the words (case-insensitive)."""
    return next((h for h in header if h.lower() in words), None)


def suggestions(header: list[str], tags: list[str]) -> dict[str, str | None]:
    """Guessed mapping fields from the column names and, for a long layout, the tag names."""
    cols = _first_by_category([h for h in header if _exact([h], TAG_NAMES + VALUE_NAMES) is None])
    by_tag = _first_by_category(tags)
    return {
        "time_col": _exact(header, TIME_NAMES) or cols["time"],
        "pv_col": cols["pv"], "out_col": cols["out"], "mode_col": cols["mode"],
        "sp_col": cols["sp"], "tag_col": _exact(header, TAG_NAMES),
        "value_col": _exact(header, VALUE_NAMES),
        "tag_pv": by_tag["pv"], "tag_out": by_tag["out"], "tag_mode": by_tag["mode"],
        "tag_sp": by_tag["sp"],
    }  # fmt: skip


def _is_long(header: list[str]) -> bool:
    """True when the header has a tag column and a value column."""
    return _exact(header, TAG_NAMES) is not None and _exact(header, VALUE_NAMES) is not None


def _head(text: str) -> str:
    """The first lines of the text (cut at a line end) for cheap layout detection."""
    if len(text) <= PREVIEW_HEAD_CHARS:
        return text
    return text[: text.rfind("\n", 0, PREVIEW_HEAD_CHARS)]


def _row_estimate(text: str) -> int:
    """Number of data rows from the line count (header excluded)."""
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    return max(0, lines - 1)


def _tag_names(text: str, header: list[str], delimiter: str) -> list[str]:
    """Distinct tag names of a long file, in order of first appearance."""
    tag_col = _exact(header, TAG_NAMES)
    full_header, rows, _ = table_from_text(text, delimiter)
    index = full_header.index(tag_col) if tag_col in full_header else 0
    return list(dict.fromkeys(r[index] for r in rows))


def preview(text: str) -> dict[str, Any]:
    """Layout, delimiter, decimal, time format, columns, first rows and mapping suggestions."""
    header, rows, delim = table_from_text(_head(text), "auto")
    long_layout = _is_long(header)
    tags = _tag_names(text, header, delim) if long_layout else []
    sugg = suggestions(header, tags)
    cells = [c for r in rows for c in r]
    decimal = "comma" if detect_decimal("auto", delim, cells) == "," else "dot"
    time_i = header.index(sugg["time_col"]) if sugg["time_col"] in header else None
    numeric = time_i is not None and bool(rows) and _looks_numeric(rows[0][time_i])
    return {
        "layout": "long" if long_layout else "wide", "delimiter": delim, "decimal": decimal,
        "time_format": "seconds" if numeric else "iso", "columns": header,
        "rows": rows[:PREVIEW_ROWS], "n_rows_estimate": _row_estimate(text),
        "suggestions": sugg, "tags": tags,
    }  # fmt: skip


def _looks_numeric(cell: str) -> bool:
    """True when the cell is a number with a dot or comma decimal mark."""
    try:
        float(cell.replace(",", "."))
    except ValueError:
        return False
    return True


def _read(request: CheckRequest) -> Record:
    """The Record of the request; a ValueError of the reader becomes a friendly 422."""
    opt = request.options
    delimiter = "\t" if opt.delimiter in ("\\t", "tab") else opt.delimiter
    given = {k: v for k, v in request.mapping.model_dump().items() if v}
    options = ReadOptions(
        **given, time_format=opt.time_format, decimal=opt.decimal, delimiter=delimiter,
        manual_value=opt.manual_value,
    )  # fmt: skip
    try:
        return read_record_text(_text(request), options)
    except ValueError as error:
        raise _unprocessable(str(error)) from error


def _run_check(rec: Record) -> StepTestCheck:
    """The StepTestCheck of a record (422 when the times cannot be used)."""
    try:
        return check_step_test(rec.t_s - rec.t_s[0], rec.out, rec.pv, rec.sp, rec.mode)
    except IpdtIdentificationError as error:
        raise _unprocessable(str(error)) from error


def _clean(value: Any) -> Any:
    """JSON-safe copy: NaN and infinity become null, tuples become lists."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def chart_sample(rec: Record, step_s: float) -> dict[str, Any]:
    """The record on its uniform grid, thinned to at most 800 points: t_s, pv, out."""
    keep = np.isfinite(rec.t_s) & np.isfinite(rec.pv) & np.isfinite(rec.out)
    t = rec.t_s[keep]
    grid, cols = resample_uniform(t, {"pv": rec.pv[keep], "out": rec.out[keep]}, step_s)
    pick = np.unique(np.linspace(0, len(grid) - 1, min(len(grid), MAX_CHART_POINTS)).astype(int))
    sample: dict[str, Any] = _clean({
        "t_s": (grid - grid[0])[pick].tolist(), "pv": cols["pv"][pick].tolist(),
        "out": cols["out"][pick].tolist(),
    })  # fmt: skip
    return sample


def _note_dicts(notes: Iterable[Note]) -> list[dict[str, Any]]:
    """Coded notes as JSON objects: code, English text and params."""
    return [_clean(asdict(note)) for note in notes]


def check_payload(rec: Record, check: StepTestCheck) -> dict[str, Any]:
    """JSON document of a check: all fields, the reading notes and the chart sample."""
    step = max(1.0, float(round(check.dt_median_s)))
    document = _clean(asdict(check))
    return {
        **document, "read_as": list(rec.assumptions), "read_as_notes": _note_dicts(rec.notes),
        "sample": chart_sample(rec, step),
    }  # fmt: skip


class _Intake:
    """Handlers of the intake routes; ``root`` is the data root."""

    def __init__(self, root: Path, loops_of: Callable[[str], list[LoopTags]]) -> None:
        self.root = root
        self.loops_of = loops_of

    def preview(self, request: PreviewRequest) -> dict[str, Any]:
        """Describe an uploaded CSV so the wizard can ask for the mapping."""
        try:
            return dict(_clean(preview(_text(request))))
        except ValueError as error:
            raise _unprocessable(str(error)) from error

    def check(self, request: CheckRequest) -> dict[str, Any]:
        """Pre-flight check and wizard dry run of the mapped record."""
        rec = _read(request)
        return check_payload(rec, _run_check(rec))

    def dataset(self, request: DatasetRequest) -> dict[str, Any]:
        """Create the dataset folder from a usable record (409 if it exists)."""
        out_dir = self._new_dir(request.dataset_id)
        rec = _read(request)
        check = _run_check(rec)
        if check.verdict == "not_usable":
            codes = [f.code for f in check.findings]
            raise _unprocessable({"message": "the record is not usable", "finding_codes": codes})
        notes = self._write(rec, out_dir, request)
        loops = [asdict(loop) for loop in self.loops_of(request.dataset_id)]
        return {
            "dataset_id": request.dataset_id, "assumptions": [n.text for n in notes],
            "assumption_notes": _note_dicts(notes), "loops": _clean(loops),
        }

    def _new_dir(self, dataset_id: str) -> Path:
        """The not-yet-existing dataset directory directly under the root (409 if present)."""
        out_dir = (self.root / dataset_id).resolve()
        if out_dir.parent != self.root.resolve() or dataset_id.startswith("_"):
            raise _unprocessable("invalid dataset id")
        if out_dir.exists():
            raise HTTPException(status_code=409, detail=f"dataset '{dataset_id}' already exists")
        return out_dir

    def _write(self, rec: Record, out_dir: Path, request: DatasetRequest) -> list[Note]:
        """Write the dataset; a failure removes the half-written folder."""
        spec = DatasetSpec(
            request.loop_name, request.process_kind, request.pv_unit, request.out_unit
        )
        try:
            return write_step_test_notes(rec, out_dir, spec)
        except FileExistsError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ValueError, OSError) as error:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise _unprocessable(f"could not write the dataset: {error}") from error


def build_intake_router(root: Path, loops_of: Callable[[str], list[LoopTags]]) -> APIRouter:
    """Routes POST /intake/preview, /intake/check and /intake/dataset."""
    handlers = _Intake(root, loops_of)
    router = APIRouter(dependencies=[Depends(_cap_body)])
    router.add_api_route("/intake/preview", handlers.preview, methods=["POST"])
    router.add_api_route("/intake/check", handlers.check, methods=["POST"])
    router.add_api_route("/intake/dataset", handlers.dataset, methods=["POST"], status_code=201)
    return router
