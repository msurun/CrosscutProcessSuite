"""Replay a recorded dataset through the advisory supervisor (ADR 010, S7).

Slides a window over the data; per step module 1 rates the gating loops, the gate state and the
window-mean fuzzy snapshot go to ``advise``. Dataset replay only: nothing here touches a plant.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from crosscut_fuzzy.model import FuzzySystem
from crosscut_loops.overview import LoopTags, analyze_dataset

from crosscut_supervisor.advise import Advice, advise
from crosscut_supervisor.audit import AuditLog
from crosscut_supervisor.config import SupervisorConfig
from crosscut_supervisor.gates import gate_state


class ReplayError(ValueError):
    """Replay input that cannot be used (unmapped or ambiguous variable, missing loop column)."""


@dataclass(frozen=True)
class ReplayData:
    """Recorded series: ``t_s`` (seconds, ascending) and equally long columns by tag id."""

    t_s: np.ndarray
    columns: Mapping[str, np.ndarray]


@dataclass(frozen=True)
class ReplaySettings:
    """Window length, step and the earliest step time (None = end of the first full window)."""

    window_s: float = 1800.0
    step_s: float = 300.0
    min_start_s: float | None = None

    def __post_init__(self) -> None:
        """Reject a non-positive window or step."""
        if self.window_s <= 0 or self.step_s <= 0:
            raise ReplayError("window_s and step_s must be positive")


@dataclass
class _State:
    """Debounce and transition memory carried from step to step."""

    last_kept_ns: int | None = None
    previous_gate: tuple[str, tuple[str, ...]] | None = None
    kept: list[Advice] = field(default_factory=list)


_Inputs = tuple[ReplayData, list[LoopTags], Mapping[str, str]]  # window, loops, variable->column


def advise_series(
    system: FuzzySystem,
    config: SupervisorConfig,
    data: ReplayData,
    loops: Sequence[LoopTags],
    settings: ReplaySettings,
) -> list[Advice]:
    """Advices the supervisor would have produced over ``data``, in time order.

    For each step time t (first full window to the end, every ``step_s``) the last ``window_s``
    of the data are cut; module 1 analyses the gating loops and the target loop; the fuzzy
    snapshot is the NaN-ignoring mean of every input over the window. ``t_ns`` is
    ``int(t * 1e9)`` of the window end.

    Debounce: a non-hold advice closer than ``config.min_interval_s`` to the previously kept
    non-hold advice is dropped. Transition logging: a blocked-hold record is kept only when the
    gate state or reasons differ from the previous step, so a long fault gives one record at its
    start (and another at every change), not one per step.

    Performance: ``analyze_dataset`` on the gating loops costs about 2 ms per 30 min window
    (180 samples at 10 s); measured 0.52 s for a 24 h replay (283 windows, 2 loops), so no cache.

    Raises:
        ReplayError: a fuzzy input matches no column or several, or a loop column is missing.
    """
    names = {gate.loop for gate in config.gates} | {config.target_loop}
    chosen = [loop for loop in loops if loop.name in names]
    _check_loop_columns(chosen, data)
    mapping = _map_inputs(system, data)
    state = _State()
    for t_end in _step_times(data.t_s, settings):
        window = _slice(data, t_end, settings.window_s)
        _step(system, config, (window, chosen, mapping), (t_end, state))
    return state.kept


def replay_to_log(advices: Sequence[Advice], log: AuditLog) -> int:
    """Append every advice as a hash-chained record; return how many were written."""
    for advice in advices:
        log.append(advice.to_record())
    return len(advices)


def _step(
    system: FuzzySystem,
    config: SupervisorConfig,
    inputs: _Inputs,
    clock: tuple[float, _State],
) -> None:
    """Evaluate one window and update the state (debounce, transition log, kept advices)."""
    window, loops, mapping = inputs
    t_end, state = clock
    rows = analyze_dataset(window.t_s, window.columns, loops) if loops else []
    gate = gate_state(rows, config)
    advice = advise(system, config, _window_means(window, mapping), gate, int(t_end * 1e9))
    seen = advice.gate if advice is not None else gate
    signature = (seen.state, seen.reasons)
    changed = signature != state.previous_gate
    state.previous_gate = signature
    if advice is not None and _keep(advice, config, state, changed):
        state.kept.append(advice)


def _keep(advice: Advice, config: SupervisorConfig, state: _State, changed: bool) -> bool:
    """Transition logging for blocked-holds, ``min_interval_s`` debounce for other advices."""
    if advice.gate.state == "blocked":
        return changed
    limit_ns = int(config.min_interval_s * 1e9)
    if state.last_kept_ns is not None and advice.t_ns - state.last_kept_ns < limit_ns:
        return False
    state.last_kept_ns = advice.t_ns
    return True


def _step_times(t_s: np.ndarray, settings: ReplaySettings) -> list[float]:
    """Window end times: from the first full window (or ``min_start_s``) to the last sample."""
    if len(t_s) == 0:
        return []
    first = float(t_s[0]) + settings.window_s
    if settings.min_start_s is not None:
        first = max(first, settings.min_start_s)
    count = int(math.floor((float(t_s[-1]) - first) / settings.step_s + 1e-9)) + 1
    return [first + k * settings.step_s for k in range(max(count, 0))]


def _slice(data: ReplayData, t_end: float, window_s: float) -> ReplayData:
    """Samples in (t_end - window_s, t_end] of every column."""
    stop = int(np.searchsorted(data.t_s, t_end, side="right"))
    start = int(np.searchsorted(data.t_s, t_end - window_s, side="right"))
    return ReplayData(
        data.t_s[start:stop], {tag: column[start:stop] for tag, column in data.columns.items()}
    )


def _window_means(window: ReplayData, mapping: Mapping[str, str]) -> dict[str, float | None]:
    """Mean of each mapped column over the window, ignoring NaN (NaN when none is finite)."""
    result: dict[str, float | None] = {}
    for variable_id, column in mapping.items():
        values = window.columns[column]
        finite = values[np.isfinite(values)]
        result[variable_id] = float(finite.mean()) if finite.size else float("nan")
    return result


def _map_inputs(system: FuzzySystem, data: ReplayData) -> dict[str, str]:
    """Dataset column of every fuzzy input: tag id, id itself, else the unique '.<id>' suffix."""
    return {variable.id: _column_for(variable.id, variable.tag, data) for variable in system.inputs}


def _column_for(variable_id: str, tag: str | None, data: ReplayData) -> str:
    """Resolve one variable to a column name or raise ReplayError naming the variable."""
    for exact in (tag, variable_id):
        if exact is not None and exact in data.columns:
            return exact
    ends = sorted(name for name in data.columns if name.endswith("." + variable_id))
    if len(ends) == 1:
        return ends[0]
    if ends:
        raise ReplayError(f"fuzzy input {variable_id!r} is ambiguous: {ends}")
    raise ReplayError(f"fuzzy input {variable_id!r} has no matching column")


def _check_loop_columns(loops: Sequence[LoopTags], data: ReplayData) -> None:
    """Every pv/sp/out/mode column of the analysed loops must exist."""
    for loop in loops:
        for tag in (loop.pv, loop.sp, loop.out, loop.mode):
            if tag not in data.columns:
                raise ReplayError(f"loop {loop.name!r}: column {tag!r} is missing")
