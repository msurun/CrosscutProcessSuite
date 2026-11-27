"""Model predictive controller on the runtime host (Phase 7.3, #184).

Wraps the ``crosscut_mpc`` engine in the ``Controller`` protocol. The controller never writes:
each cycle returns one setpoint move per MV (the engine's first move, absolute engineering
units) and the host hands moves to the gateway as proposals, exactly like the fuzzy controller.
The gateway mode (advisory, confirm, supervised) and the roles of ADR 013 decide what is written.

Start is bumpless (ADR 018): ``initialise`` forgets the engine state; the next ``step`` reads the
live values, takes them as the operating point and returns the current setpoints (a zero move).
A bad input holds the MVs and the next good cycle starts bumpless again. After the engine's shed
rule (3 cycles without a feasible plan) the result asks the host to shed to base control.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from crosscut_mpc.config import Controller, Settings
from crosscut_mpc.engine import ControllerState, Result, cycle, initialise
from crosscut_mpc.planning import CycleInputs

from crosscut_runtime.controllers import mpc_report as report
from crosscut_runtime.controllers.mpc_limits import (
    LimitsError,
    build_economics,
    build_limits,
    clamp_move,
    range_of,
)
from crosscut_runtime.controllers.mpc_model import BoundModel
from crosscut_runtime.controllers.protocol import Move, StepResult
from crosscut_runtime.variable_status import DEFAULT_CYCLE_S, GOOD, VariableStatus


class MpcBindingError(ValueError):
    """The catalogue does not fit the model or lacks a limit the engine needs."""


@dataclass(frozen=True)
class Live:
    """Live values of one cycle: MV setpoints, CV values and DV values in model order."""

    sp: np.ndarray
    cv: np.ndarray
    dv: np.ndarray


@dataclass
class _Run:
    """The operating point taken at the start and the engine state since then."""

    ref: Live
    state: ControllerState


class MpcController:
    """Implements the Controller protocol for an identified MIMO model."""

    def __init__(
        self, controller_doc: Mapping[str, Any], model: BoundModel, mv_targets: Mapping[str, str]
    ) -> None:
        """Bind the model; ``MpcBindingError`` when a limit or an MV target is missing."""
        self.id = str(controller_doc["id"])
        self._cycle_s = float(controller_doc.get("cycle_s", DEFAULT_CYCLE_S))
        self._model, self._targets = model, dict(mv_targets)
        config = controller_doc["mpc"]
        self._settings = Settings(
            config.get("prediction_horizon", 60), config.get("move_horizon", 8),
            config.get("move_suppression", 1.0),
        )
        missing = [name for name in model.mv_ids if not mv_targets.get(name)]
        if missing:
            raise MpcBindingError(f"no gateway target for MV {missing[0]!r}")
        self._vars = {v["id"]: v for v in controller_doc["variables"]}
        self._economics: Mapping[str, Any] | None = config.get("economics")
        self._run: _Run | None = None
        self._last: dict[str, float] = {}  # last proposed setpoint of each MV
        self._recover = False  # the last cycle held: the next solved cycle restarts bumpless
        self._engine(Live(np.zeros(len(model.mv_ids)), np.zeros(len(model.cv_ids)), np.zeros(0)))

    def apply_limits(self, variables: Sequence[Mapping[str, Any]]) -> None:
        """Take the limits of the effective variables (catalogue plus operator overrides)."""
        self._vars = {v["id"]: v for v in variables}

    def apply_economics(self, block: Mapping[str, Any] | None) -> None:
        """Take the objective of this cycle (operator override or catalogue); ``None`` = none."""
        self._economics = block

    def initialise(self, statuses: Sequence[VariableStatus]) -> None:
        """Forget the engine state; the next step starts bumpless at the live values."""
        del statuses
        self._run, self._recover = None, False
        self._last.clear()

    def step(self, statuses: Sequence[VariableStatus]) -> StepResult:
        """One cycle: read inputs, run the engine, return one move per MV with its reason."""
        live = self._read({s.variable_id: s for s in statuses})
        if isinstance(live, list):
            self._run, self._recover = None, False
            self._last.clear()
            data, text = report.input_bad_report(self._model.mv_ids, live)
            return StepResult((), text, data)
        if self._run is None:
            self._run = self._start(live)
        inputs = self._inputs(live, self._run.ref)
        result, self._run.state = cycle(self._engine(self._run.ref), self._run.state, inputs)
        if report.status_of(result) == report.SOLVED and self._recover:
            # Recovery after a hold is bumpless again: restart at the live values, zero move.
            self._run, self._recover = self._start(live), False
            self._last.clear()
            inputs = self._inputs(live, self._run.ref)
            result, self._run.state = cycle(self._engine(self._run.ref), self._run.state, inputs)
        self._recover = self._recover or report.status_of(result) == report.HOLD
        return self._result(result, live)

    def _read(self, by_id: Mapping[str, VariableStatus]) -> Live | list[str]:
        """Live values in model order, or the ids of the unusable variables."""
        model = self._model

        def pick(names: Sequence[str], attr: str) -> list[float | None]:
            return [_usable(by_id.get(name), attr) for name in names]

        sp, cv, dv = pick(model.mv_ids, "sp_value"), pick(model.cv_ids, "value"), pick(
            model.dv_ids, "value")
        names = (*model.mv_ids, *model.cv_ids, *model.dv_ids)
        bad = [n for n, v in zip(names, (*sp, *cv, *dv), strict=True) if v is None]
        return bad or Live(np.array(sp), np.array(cv), np.array(dv))

    def _start(self, live: Live) -> _Run:
        """Take the live values as the operating point and start the engine there."""
        return _Run(live, initialise(self._engine(live), self._inputs(live, live)))

    def _engine(self, ref: Live) -> Controller:
        """The engine controller with the current limits shifted to the reference point."""
        try:
            limits = build_limits(
                self._vars, (self._model.mv_ids, self._model.cv_ids), (ref.sp, ref.cv),
                (self._cycle_s, self._settings.prediction_horizon),
            )
        except (LimitsError, ValueError) as error:
            raise MpcBindingError(str(error)) from error
        ids = (self._model.mv_ids, self._model.cv_ids)
        try:
            economics = build_economics(self._economics, self._vars, ids, (ref.sp, ref.cv))
            return Controller(self._model.plant, limits, self._settings, economics)
        except ValueError as error:
            raise MpcBindingError(f"economics: {error}") from error

    def _inputs(self, live: Live, ref: Live) -> CycleInputs:
        """Engine inputs as deviations; a CV without a target is held where it is, in range."""
        goals = []
        for index, name in enumerate(self._model.cv_ids):
            lo, hi = range_of(self._vars[name])
            goal = self._vars[name].get("target")
            goals.append(float(goal) if goal is not None else min(max(live.cv[index], lo), hi))
        return CycleInputs(live.cv - ref.cv, live.sp - ref.sp, np.array(goals) - ref.cv,
                           tuple(live.dv - ref.dv))

    def _frame(self, live: Live) -> report.Frame:
        """The report frame of this cycle."""
        assert self._run is not None
        names = (*self._model.mv_ids, *self._model.cv_ids)
        return report.Frame(
            self._model.mv_ids, self._model.cv_ids, (self._run.ref.sp, self._run.ref.cv),
            {n: range_of(self._vars[n]) for n in names},
            {n: self._vars[n].get("target") for n in self._model.cv_ids}, (live.sp, live.cv),
        )

    def _result(self, result: Result, live: Live) -> StepResult:
        """Moves, codes and diagnostics of an engine result."""
        frame = self._frame(live)
        result, invalid = self._cut(result, frame)
        frame = replace(frame, invalid=invalid)
        codes = report.mv_codes(result, frame)
        data = report.diagnostics(result, frame, codes)
        data.update(report.economics_report(result, frame))
        text = report.explanation(codes, data["why_no_move"], result.reason)
        if report.status_of(result) == report.SHED:
            return StepResult((), text, data, shed=True)
        return StepResult(self._moves(result, frame, codes), text, data)

    def _cut(self, result: Result, frame: report.Frame) -> tuple[Result, frozenset[str]]:
        """The result with every MV move cut to the step windows and the range.

        A move that is not a finite number is replaced by a hold of that MV and named.
        """
        ref, sp = frame.ref[0], frame.live[0]
        cut, invalid = [], set()
        for i, name in enumerate(self._model.mv_ids):
            wanted = float(result.moves[i] + ref[i])
            if not np.isfinite(wanted):
                invalid.add(name)
                wanted = float(sp[i])
            value = clamp_move(self._vars[name], float(sp[i]), wanted, self._cycle_s,
                               self._last.get(name))
            cut.append(value - float(ref[i]))
            self._last[name] = value
        return replace(result, moves=tuple(cut)), frozenset(invalid)

    def _moves(
        self, result: Result, frame: report.Frame, codes: Mapping[str, str]
    ) -> tuple[Move, ...]:
        """One move per MV that changes its setpoint; the first cycle tracks the current one."""
        target = report.proposed(result, frame)
        moves = []
        for index, name in enumerate(self._model.mv_ids):
            current = float(frame.live[0][index])
            if codes[name] == report.BUMPLESS:
                moves.append(Move(name, self._targets[name], current, "bumpless_initialisation"))
            elif codes[name] == report.MOVE:
                reason = f"{report.MOVE}: {result.status}"
                moves.append(Move(name, self._targets[name], float(target[index]), reason))
        return tuple(moves)


def _usable(status: VariableStatus | None, attr: str) -> float | None:
    """A finite value of a good (fresh, valid) status; ``None`` for anything else."""
    value = getattr(status, attr, None) if status is not None and status.status == GOOD else None
    return float(value) if value is not None and np.isfinite(value) else None
