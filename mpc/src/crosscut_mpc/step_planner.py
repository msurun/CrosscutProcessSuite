"""Multi-MV step-test planner: a schedule of bounded setpoint proposals (MPC 7.1a, ADR 017 style).

Pure planning only. It never reads a plant, never writes and imports no gateway code: the caller
turns each planned step into a normal Write Gateway proposal in confirm mode, so a human approves
every move. Every step is validated BEFORE it is offered; a violation is refused with a stable
reason code, never clamped. All values are engineering units, all times seconds from plan start.

Plan types (the schedule is a list of absolute setpoint values per MV tag):
* ``sequential``: one MV at a time. Step to ``baseline + amplitude``, hold ``duration_s``, return to
  the baseline, wait ``gap_s``, then the next MV.
* ``gbn``: generalised binary noise, all MVs together. Each MV sits at ``baseline +/- amplitude``;
  every ``sample_s`` it flips with probability ``switch_probability`` (mean dwell
  ``sample_s / switch_probability``). The plan lasts ``duration_s`` and ends back at the baseline.
  MV ``i`` uses ``random.Random(seed * 1000 + i)``, so the same seed gives the same plan.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Literal

PlanType = Literal["sequential", "gbn"]
MAX_STEPS = 200  # a plan longer than this is a data-entry mistake, not a step test
SEED_STRIDE = 1000  # per-MV seed offset: seed * SEED_STRIDE + MV index


@dataclass(frozen=True)
class MvSpec:
    """One MV: tag, live baseline and the bounds a proposal must respect.

    ``limits`` is the intersection of the variable-model engineering/operator range and the
    gateway policy limits; ``max_step`` is the smaller of the policy ``max_step`` and the
    variable ``move_max``; ``min_interval_s`` is the policy minimum time between writes.
    """

    name: str
    tag: str
    baseline: float
    amplitude: float
    limits: tuple[float, float]
    max_step: float
    min_interval_s: float


@dataclass(frozen=True)
class PlanSettings:
    """Plan type and timing; ``sample_s`` and ``switch_probability`` apply to ``gbn`` only."""

    plan_type: PlanType
    duration_s: float
    gap_s: float = 0.0
    sample_s: float = 0.0
    switch_probability: float = 0.0
    seed: int = 0


@dataclass(frozen=True)
class PlannedStep:
    """One proposal: absolute ``value`` at ``at_s`` seconds; ``delta`` is the move from the last."""

    index: int
    mv: str
    tag: str
    at_s: float
    value: float
    delta: float


@dataclass(frozen=True)
class Refusal:
    """Why the plan cannot be offered: stable ``code``, the MV and the step it concerns."""

    mv: str
    code: str
    step: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class Plan:
    """The schedule, ordered by time; any refusal means the plan must not be offered."""

    steps: tuple[PlannedStep, ...] = ()
    refusals: tuple[Refusal, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """True only for a non-empty plan with no refusal."""
        return bool(self.steps) and not self.refusals


def _finite(*values: float) -> bool:
    """True when every value is a real finite number (not bool, NaN or infinity)."""
    return all(
        isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
        for v in values
    )


def _setting_refusals(mvs: list[MvSpec], settings: PlanSettings) -> list[Refusal]:
    """Refusals for plan-level input that makes no schedule possible."""
    if not mvs:
        return [Refusal("", "no_mv")]
    if settings.plan_type not in ("sequential", "gbn"):
        return [Refusal("", "unknown_plan_type", detail=str(settings.plan_type))]
    out: list[Refusal] = []
    if not _finite(settings.duration_s, settings.gap_s) or settings.duration_s <= 0:
        out.append(Refusal("", "bad_duration"))
    if settings.gap_s < 0:
        out.append(Refusal("", "bad_gap"))
    if settings.plan_type == "gbn":
        out += _gbn_setting_refusals(settings)
    return out


def _gbn_setting_refusals(settings: PlanSettings) -> list[Refusal]:
    """GBN needs a positive grid shorter than the plan and a switching probability in (0, 1]."""
    out: list[Refusal] = []
    if not _finite(settings.sample_s) or not 0 < settings.sample_s <= settings.duration_s:
        out.append(Refusal("", "bad_sample_s"))
    if not _finite(settings.switch_probability) or not 0 < settings.switch_probability <= 1:
        out.append(Refusal("", "bad_switch_probability"))
    return out


def _mv_refusals(mv: MvSpec) -> list[Refusal]:
    """Refusals for one MV's own bounds and baseline, before any step exists."""
    if not _finite(mv.amplitude, mv.baseline, mv.max_step, mv.min_interval_s, *mv.limits):
        return [Refusal(mv.name, "bad_value")]
    low, high = mv.limits
    if mv.amplitude == 0:
        return [Refusal(mv.name, "amplitude_zero")]
    if abs(mv.amplitude) > mv.max_step:
        return [Refusal(mv.name, "amplitude_exceeds_max_step",
                        detail=f"{abs(mv.amplitude)} > {mv.max_step}")]
    if not low <= mv.baseline <= high:
        return [Refusal(mv.name, "baseline_outside_limits", detail=f"{mv.baseline}")]
    return []


def _sequential_values(
    mvs: list[MvSpec], settings: PlanSettings
) -> list[tuple[float, MvSpec, float]]:
    """(time, MV, value) rows: out and back for each MV in turn, separated by ``gap_s``."""
    rows: list[tuple[float, MvSpec, float]] = []
    clock = 0.0
    for mv in mvs:
        rows.append((clock, mv, mv.baseline + mv.amplitude))
        rows.append((clock + settings.duration_s, mv, mv.baseline))
        clock += settings.duration_s + settings.gap_s
    return rows


def _gbn_levels(mv: MvSpec, settings: PlanSettings, index: int) -> list[float]:
    """GBN sign (+1 or -1) of each sample interval of one MV, from its own seeded generator."""
    rng = random.Random(settings.seed * SEED_STRIDE + index)
    count = int(settings.duration_s // settings.sample_s)
    sign = 1.0 if rng.random() < 0.5 else -1.0  # noqa: PLR2004 - fair coin for the first level
    levels = []
    for _ in range(count):
        if levels and rng.random() < settings.switch_probability:
            sign = -sign
        levels.append(sign)
    return levels


def _gbn_values(mvs: list[MvSpec], settings: PlanSettings) -> list[tuple[float, MvSpec, float]]:
    """(time, MV, value) rows at each level change, plus a final return to the baseline."""
    rows: list[tuple[float, MvSpec, float]] = []
    for index, mv in enumerate(mvs):
        previous = mv.baseline
        levels = _gbn_levels(mv, settings, index)
        for slot, sign in enumerate(levels):
            value = mv.baseline + sign * abs(mv.amplitude)
            if value != previous:
                rows.append((slot * settings.sample_s, mv, value))
                previous = value
        rows.append((len(levels) * settings.sample_s, mv, mv.baseline))
    return rows


def _check_step(mv: MvSpec, value: float, previous: float, gap_s: float | None) -> str:
    """Refusal code of one step against limits, ``max_step`` and the write interval; '' if fine."""
    low, high = mv.limits
    if value < low:
        return "value_below_limit"
    if value > high:
        return "value_above_limit"
    if abs(value - previous) > mv.max_step + 1e-12:
        return "step_exceeds_max_step"
    if gap_s is not None and gap_s < mv.min_interval_s:
        return "interval_below_min"
    return ""


def _validate(rows: list[tuple[float, MvSpec, float]]) -> Plan:
    """Order rows by time, check every step per MV, number them; no step survives a refusal."""
    rows = sorted(rows, key=lambda row: row[0])  # stable: equal times keep MV order
    last_value = {mv.tag: mv.baseline for _, mv, _ in rows}
    last_time: dict[str, float] = {}
    steps: list[PlannedStep] = []
    refusals: list[Refusal] = []
    for at_s, mv, value in rows:
        gap = at_s - last_time[mv.tag] if mv.tag in last_time else None
        index = len(steps) + len(refusals)
        code = _check_step(mv, value, last_value[mv.tag], gap)
        if code:
            refusals.append(Refusal(mv.name, code, index, f"t={at_s:g}s value={value:g}"))
            continue
        steps.append(PlannedStep(index, mv.name, mv.tag, at_s, value, value - last_value[mv.tag]))
        last_value[mv.tag], last_time[mv.tag] = value, at_s
    if len(steps) > MAX_STEPS:
        return Plan((), (Refusal("", "too_many_steps", detail=f"{len(steps)} > {MAX_STEPS}"),))
    if refusals:  # a plan with one refused step is not offered at all
        return Plan((), tuple(refusals))
    return Plan(tuple(steps), ())


def build_plan(mvs: list[MvSpec], settings: PlanSettings) -> Plan:
    """Build and validate a plan; the result is offerable only when ``Plan.ok``.

    Refusal codes: ``no_mv``, ``unknown_plan_type``, ``bad_duration``, ``bad_gap``,
    ``bad_sample_s``, ``bad_switch_probability``, ``bad_value``, ``amplitude_zero``,
    ``amplitude_exceeds_max_step``, ``baseline_outside_limits``, ``value_below_limit``,
    ``value_above_limit``, ``step_exceeds_max_step``, ``interval_below_min``, ``too_many_steps``.
    """
    refusals = _setting_refusals(mvs, settings)
    for mv in mvs:
        refusals += _mv_refusals(mv)
    if refusals:
        return Plan((), tuple(refusals))
    rows = (_sequential_values if settings.plan_type == "sequential" else _gbn_values)(
        mvs, settings
    )
    return _validate(rows)
