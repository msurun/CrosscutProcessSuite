"""Operator-facing result of one MPC cycle: per-MV reason codes, why no move, diagnostics.

``diagnostics`` is plain JSON for the console: CV and MV limits, predicted CV trajectories,
active constraints, relaxed CVs and the reason the controller did not move. Pure functions.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from crosscut_mpc.engine import SHED_CYCLES, Result

BUMPLESS, HOLD, SHED = "bumpless_start", "hold", "shed"
INPUT_BAD, LIMIT, NO_TARGET = "input_bad", "limit", "no_target"
MOVE, AT_TARGET, SOLVED = "move", "at_target", "solved"
WHY_ORDER = (SHED, INPUT_BAD, HOLD, BUMPLESS, LIMIT, NO_TARGET, AT_TARGET)
MAX_CONSTRAINTS = 40
CONSTRAINT = re.compile(r"(mv|cv)\[(\d+)\]\.(lower|upper)@(\d+)")
Range = tuple[float, float]


@dataclass(frozen=True)
class Frame:
    """What a report needs besides the engine result: names, reference, ranges, targets, values."""

    mv_ids: tuple[str, ...]
    cv_ids: tuple[str, ...]
    ref: tuple[np.ndarray, np.ndarray]  # (MV reference, CV reference)
    ranges: Mapping[str, Range]
    targets: Mapping[str, float | None]
    live: tuple[np.ndarray, np.ndarray]  # (MV setpoints, CV values)


def moved(proposed: float, current: float) -> bool:
    """True when the proposal differs from the current setpoint."""
    return not math.isclose(proposed, current, rel_tol=1e-9, abs_tol=1e-9)


def proposed(result: Result, frame: Frame) -> np.ndarray:
    """Absolute MV setpoints of the engine's first move."""
    return np.asarray(result.moves) + frame.ref[0]


def constraints(result: Result, frame: Frame) -> list[dict[str, Any]]:
    """Active constraint labels of the engine as ``{kind, variable, side, sample}``."""
    out = []
    for label in result.active_constraints[:MAX_CONSTRAINTS]:
        match = CONSTRAINT.fullmatch(label)
        if match is None:
            continue
        kind, index, side, sample = match.groups()
        names = frame.mv_ids if kind == "mv" else frame.cv_ids
        out.append({"kind": kind.upper(), "variable": names[int(index)], "side": side,
                    "sample": int(sample)})
    return out


def status_of(result: Result) -> str:
    """Engine status in the report vocabulary."""
    return {"initialised": BUMPLESS, "hold": HOLD, "shed": SHED}.get(result.status, SOLVED)


def mv_codes(result: Result, frame: Frame) -> dict[str, str]:
    """One reason code per MV: why it moved or why it did not."""
    status = status_of(result)
    active = constraints(result, frame)
    at_limit = {c["variable"] for c in active if c["kind"] == "MV" and c["sample"] == 1}
    aimed = any(t is not None for t in frame.targets.values()) or any(
        c["kind"] == "CV" for c in active
    )
    target = proposed(result, frame)
    codes = {}
    for index, name in enumerate(frame.mv_ids):
        if status != SOLVED:
            codes[name] = status
        elif moved(float(target[index]), float(frame.live[0][index])):
            codes[name] = MOVE
        else:
            codes[name] = LIMIT if name in at_limit else (AT_TARGET if aimed else NO_TARGET)
    return codes


def why_no_move(codes: Mapping[str, str]) -> str | None:
    """The common reason when no MV moves; ``None`` as soon as one MV moves."""
    if MOVE in codes.values():
        return None
    return min(codes.values(), key=WHY_ORDER.index)


def diagnostics(result: Result, frame: Frame, codes: Mapping[str, str]) -> dict[str, Any]:
    """The console payload of one cycle."""
    path = np.asarray(result.predicted_cvs).reshape(-1, len(frame.cv_ids)) + frame.ref[1]
    relaxed = {frame.cv_ids[i] for i in result.relaxed_cvs}
    target = proposed(result, frame)
    return {
        "kind": "mpc",
        "status": status_of(result),
        "reason": result.reason,
        "why_no_move": why_no_move(codes),
        "shed_after": SHED_CYCLES,
        "cvs": [
            {"id": name, "value": float(frame.live[1][i]), "target": frame.targets[name],
             "lo": frame.ranges[name][0], "hi": frame.ranges[name][1],
             "relaxed": name in relaxed, "predicted": [float(v) for v in path[:, i]]}
            for i, name in enumerate(frame.cv_ids)
        ],
        "mvs": [
            {"id": name, "sp": float(frame.live[0][i]), "proposed": float(target[i]),
             "lo": frame.ranges[name][0], "hi": frame.ranges[name][1], "code": codes[name]}
            for i, name in enumerate(frame.mv_ids)
        ],
        "active_constraints": constraints(result, frame),
    }


def explanation(codes: Mapping[str, str], why: str | None, reason: str) -> str:
    """One line for the record: the MV codes and, when nothing moves, why."""
    text = " | ".join(f"{name}: {code}" for name, code in codes.items())
    extra = [part for part in (f"why_no_move={why}" if why else "", reason) if part]
    return text + (f" [{'; '.join(extra)}]" if extra else "")


def input_bad_report(
    mv_ids: Sequence[str], missing: Sequence[str]
) -> tuple[dict[str, Any], str]:
    """Diagnostics and explanation of a cycle skipped because inputs were unusable."""
    codes = {name: INPUT_BAD for name in mv_ids}
    note = f"unusable inputs: {', '.join(missing)}"
    data = {"kind": "mpc", "status": INPUT_BAD, "reason": note, "why_no_move": INPUT_BAD,
            "shed_after": SHED_CYCLES, "cvs": [], "mvs": [], "active_constraints": []}
    return data, explanation(codes, INPUT_BAD, note)
