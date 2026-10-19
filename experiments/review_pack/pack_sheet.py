"""Writers for the reviewer-facing files: self-contained HTML sheet, instructions, template.

The sheet draws PV/SP and OP trends as hand-written inline SVG (no external assets) and
adds an answer form per loop with a CSV export button. Nothing here reveals the injected
cause of a loop: only tag, unit, engineering range and the recorded signals are shown.
"""

from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pack_catalog import KINDS
from pack_sheet_assets import CSS, INSTRUCTIONS, SCRIPT

if TYPE_CHECKING:
    from make_pack import LoopData

CATEGORIES = [
    "none",
    "valve/stiction",
    "tuning aggressive",
    "tuning sluggish",
    "external disturbance",
    "saturation",
    "manual",
    "measurement/instrument",
    "other",
]
W, H = 960, 190
LEFT, RIGHT, TOP, BOTTOM = 62, 12, 10, 22


def _nice(value: float) -> str:
    """Compact number label for an axis tick."""
    return f"{value:.4g}"


def _xy(t_s: np.ndarray, values: np.ndarray, lo: float, hi: float) -> str:
    """SVG ``points`` string for a series scaled into the plot area."""
    xs = LEFT + (t_s - t_s[0]) / (t_s[-1] - t_s[0]) * (W - LEFT - RIGHT)
    ys = TOP + (1 - (values - lo) / (hi - lo)) * (H - TOP - BOTTOM)
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))


def _grid(t_s: np.ndarray, lo: float, hi: float) -> str:
    """Grid lines and tick labels: 5 horizontal levels and one vertical line per hour."""
    parts = []
    for i in range(5):
        value = lo + (hi - lo) * i / 4
        y = TOP + (1 - i / 4) * (H - TOP - BOTTOM)
        parts.append(f'<line class="g" x1="{LEFT}" x2="{W - RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="t" x="{LEFT - 5}" y="{y + 4:.1f}" text-anchor="end">'
            f"{_nice(value)}</text>"
        )
    for hour in range(int(t_s[-1] // 3600) + 1):
        x = LEFT + hour * 3600 / (t_s[-1] - t_s[0]) * (W - LEFT - RIGHT)
        parts.append(f'<line class="g" x1="{x:.1f}" x2="{x:.1f}" y1="{TOP}" y2="{H - BOTTOM}"/>')
        parts.append(
            f'<text class="t" x="{x:.1f}" y="{H - 6}" text-anchor="middle">{hour} h</text>'
        )
    return "".join(parts)


def _manual_band(t_s: np.ndarray, mode: np.ndarray) -> str:
    """Grey rectangles over the stretches where the loop is in MANUAL (mode code 0)."""
    span = (W - LEFT - RIGHT) / (len(t_s) - 1)
    manual = np.append(mode == 0, False)
    out, start = [], None
    for k, flag in enumerate(manual):
        if flag and start is None:
            start = k
        elif not flag and start is not None:
            out.append(
                f'<rect class="man" x="{LEFT + start * span:.1f}" y="{TOP}" '
                f'width="{(k - start) * span:.1f}" height="{H - TOP - BOTTOM}"/>'
            )
            out.append(
                f'<text class="t" x="{LEFT + start * span + 4:.1f}" y="{TOP + 12}">MAN</text>'
            )
            start = None
    return "".join(out)


def _panel(title: str, body: str) -> str:
    """One SVG panel with a caption."""
    return (
        f'<div class="panel"><div class="cap">{html.escape(title)}</div>'
        f'<svg viewBox="0 0 {W} {H}" role="img">{body}</svg></div>'
    )


def _pv_panel(loop: LoopData) -> str:
    """PV (solid) and SP (dashed) over the whole record, with a fair vertical scale."""
    info = KINDS[loop.spec.kind]
    lo = min(loop.pv.min(), loop.sp.min())
    hi = max(loop.pv.max(), loop.sp.max())
    span = max((hi - lo) * 1.1, 0.05 * (info.eng_max - info.eng_min))
    mid = (hi + lo) / 2
    lo, hi = mid - span / 2, mid + span / 2
    body = _grid(loop.t_s, lo, hi)
    body += f'<polyline class="sp" points="{_xy(loop.t_s, loop.sp, lo, hi)}"/>'
    body += f'<polyline class="pv" points="{_xy(loop.t_s, loop.pv, lo, hi)}"/>'
    return _panel(f"PV (solid) and SP (dashed), {info.unit}", body)


def _op_panel(loop: LoopData) -> str:
    """Controller output (0-100 %) over the whole record, MANUAL stretches shaded."""
    body = _grid(loop.t_s, 0.0, 100.0) + _manual_band(loop.t_s, loop.mode)
    body += f'<polyline class="op" points="{_xy(loop.t_s, loop.op, 0.0, 100.0)}"/>'
    return _panel("Controller output OP, % (grey = MANUAL)", body)


def _form(loop: LoopData) -> str:
    """The answer form of one loop (rank, category, next action, confidence)."""
    options = "".join(f"<option>{html.escape(c)}</option>" for c in CATEGORIES)
    conf = "".join(f"<option>{i}</option>" for i in range(1, 6))
    return (
        '<div class="form">'
        '<label>Priority rank (1-20)<input type="number" min="1" max="20" class="rank"></label>'
        f'<label>Problem category<select class="cat"><option value=""></option>{options}'
        "</select></label>"
        '<label class="wide">Next action<textarea class="act" rows="3"></textarea></label>'
        f'<label>Confidence (1-5)<select class="conf"><option value=""></option>{conf}'
        "</select></label></div>"
    )


def _section(loop: LoopData) -> str:
    """Heading, the two trend panels and the form of one loop."""
    info = KINDS[loop.spec.kind]
    kind = "integrating (level)" if loop.spec.integrating else "self-regulating"
    head = (
        f"<h2>{loop.tag} <small>unit {html.escape(info.unit)}, range "
        f"{_nice(info.eng_min)}-{_nice(info.eng_max)}, {kind}, 6 h at 10 s</small></h2>"
    )
    return (
        f'<section data-tag="{loop.tag}">{head}{_pv_panel(loop)}{_op_panel(loop)}'
        f"{_form(loop)}</section>"
    )


def write_review_sheet(loops: list[LoopData], path: Path) -> None:
    """Write the self-contained ``review_sheet.html`` for all loops."""
    body = "".join(_section(loop) for loop in loops)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Loop review sheet</title><style>{CSS}</style></head><body>"
        "<header><h1>Loop review sheet</h1>"
        "<p>Rank all 20 loops (1 = you would look at it first on a plant), pick a category, "
        "write the next action and your confidence. Then export your answers.</p>"
        '<button id="export">Export answers CSV</button> <span id="status"></span></header>'
        f"{body}<script>{SCRIPT}</script></body></html>"
    )
    path.write_text(page, encoding="utf-8")


def write_instructions(loops: list[LoopData], out_dir: Path) -> None:
    """Write ``reviewer_instructions.md`` and the empty ``answers_template.csv``."""
    text = INSTRUCTIONS.replace("{categories}", "\n".join(f"- {c}" for c in CATEGORIES))
    (out_dir / "reviewer_instructions.md").write_text(text, encoding="utf-8")
    with open(out_dir / "answers_template.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tag", "rank", "category", "next_action", "confidence"])
        for loop in loops:
            writer.writerow([loop.tag, "", "", "", ""])
