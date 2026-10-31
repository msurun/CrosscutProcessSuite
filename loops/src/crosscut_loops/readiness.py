"""Check whether a historian export is good enough for loop monitoring and stiction detection.

Before a customer sends a historian export, this module checks whether it is good enough for loop
monitoring and stiction detection. It returns a report with one check per problem, each check
saying what to fix and why.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from crosscut_loops.metrics import flatline_fraction
from crosscut_loops.overview import LoopTags

# --- Thresholds (warn / fail pairs; the duration limits are minima, the others maxima) ---

MIN_DURATION_H = 6.0  # a shorter record is a fail, in hours
WARN_DURATION_H = 24.0  # a shorter record is a warning, in hours
STICTION_PERIOD_S = 15.0  # slower sampling hides valve stiction (warn), in seconds
FAIL_PERIOD_S = 60.0  # slower sampling is too coarse for loop analysis (fail), in seconds
IRREGULAR_STEP_FRACTION = 0.5  # a step this far from the median period is irregular, in [0, 1]
WARN_IRREGULAR_SHARE = 0.05  # share of irregular steps that triggers a warning, in [0, 1]
WARN_NAN_SHARE = 0.05  # share of missing values that triggers a warning, in [0, 1]
FAIL_NAN_SHARE = 0.30  # share of missing values that fails the tag, in [0, 1]
WARN_FLAT_SHARE = 0.50  # share of samples in flat runs that triggers a warning, in [0, 1]
FAIL_FLAT_SHARE = 0.90  # share of samples in flat runs that fails the tag, in [0, 1]
FLAT_RUN_MINUTES = 10.0  # a stuck signal repeats its value this long, in minutes
MIN_FLAT_RUN_SAMPLES = 3  # a flat run is at least this many identical samples, however coarse
SECONDS_PER_HOUR = 3600.0

REQUIRED_ROLES = ("pv", "sp")  # a missing tag of these roles fails the loop
MOVING_ROLES = ("pv", "out")  # signals that must vary; SP and MODE may sit still for days

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class ReadinessConfig:
    """Thresholds and parameters for data readiness and onboarding checks."""

    min_duration_h: float = MIN_DURATION_H
    warn_duration_h: float = WARN_DURATION_H
    max_sample_period_s: float = FAIL_PERIOD_S
    warn_sample_period_s: float = STICTION_PERIOD_S
    max_missing_share: float = FAIL_NAN_SHARE
    warn_missing_share: float = WARN_NAN_SHARE
    max_flat_share: float = FAIL_FLAT_SHARE
    warn_flat_share: float = WARN_FLAT_SHARE
    min_anomaly_inputs: int = 2
    min_softsensor_inputs: int = 2


@dataclass(frozen=True)
class Check:
    """One finding of the readiness check.

    ``name`` is a short id such as "duration" or "flat:<tag name>"; ``status`` is "ok", "warn"
    or "fail"; ``message`` is one plain sentence with the measured number and its unit.
    """

    name: str
    status: str
    message: str


@dataclass(frozen=True)
class ReadinessReport:
    """All checks of one export; ``ready`` means nothing failed (warnings are allowed)."""

    checks: tuple[Check, ...]

    @property
    def ready(self) -> bool:
        """True when no check has status "fail"."""
        return not self.failures()

    def failures(self) -> list[Check]:
        """Checks with status "fail"."""
        return [check for check in self.checks if check.status == FAIL]

    def warnings(self) -> list[Check]:
        """Checks with status "warn"."""
        return [check for check in self.checks if check.status == WARN]


def check_readiness(
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    loops: Sequence[LoopTags],
    config: ReadinessConfig | None = None,
) -> ReadinessReport:
    """Check whether an export is good enough for loop monitoring and stiction detection.

    ``t_s`` are the timestamps in seconds, ``columns`` the series by tag name, ``loops`` the
    loops the customer wants analysed. The record needs at least two timestamps.
    """
    cfg = config or ReadinessConfig()
    if len(t_s) < 2:
        return ReadinessReport((Check("duration", FAIL, "The record has fewer than 2 samples."),))
    time_checks = _check_time_steps(t_s, cfg)
    checks = [_check_duration(t_s, cfg), *time_checks]
    if any(check.status == FAIL for check in time_checks):
        return ReadinessReport(tuple(checks))  # the per-tag checks divide by the time step
    for loop in loops:
        checks.extend(_check_loop(t_s, columns, loop, cfg))
    return ReadinessReport(tuple(checks))


def _check_duration(t_s: np.ndarray, cfg: ReadinessConfig) -> Check:
    """Fail below min_duration_h, warn below warn_duration_h."""
    hours = float(t_s[-1] - t_s[0]) / SECONDS_PER_HOUR
    if hours < cfg.min_duration_h:
        msg = f"The record is {hours:.1f} h long; {cfg.min_duration_h:.1f} h are needed."
        return Check("duration", FAIL, msg)
    if hours < cfg.warn_duration_h:
        msg = f"The record is {hours:.1f} h long; {cfg.warn_duration_h:.1f} h is better."
        return Check("duration", WARN, msg)
    return Check("duration", OK, f"The record is {hours:.1f} h long.")


def _check_time_steps(t_s: np.ndarray, cfg: ReadinessConfig) -> list[Check]:
    """Sample period, regularity and ordering of the timestamps."""
    steps = np.diff(t_s)
    if not np.all(np.isfinite(t_s)) or np.any(steps <= 0):
        return [Check("time_order", FAIL, "Timestamps are missing, repeated or out of order.")]
    return [_check_period(float(np.median(steps)), cfg), _check_regularity(steps)]


def _check_period(period_s: float, cfg: ReadinessConfig) -> Check:
    """Sample period: above warn hides valve stiction, above max is too coarse."""
    if period_s > cfg.max_sample_period_s:
        msg = f"Samples are {period_s:.0f} s apart; {cfg.max_sample_period_s:.0f} s is max."
        return Check("sample_period", FAIL, msg)
    if period_s > cfg.warn_sample_period_s:
        msg = (
            f"Samples are {period_s:.0f} s apart; slower than about "
            f"{cfg.warn_sample_period_s:.0f} s hides valve stiction."
        )
        return Check("sample_period", WARN, msg)
    return Check("sample_period", OK, f"Samples are {period_s:.1f} s apart.")


def _check_regularity(steps: np.ndarray) -> Check:
    """Share of time steps that differ from the median step by more than half of it."""
    median = float(np.median(steps))
    share = float(np.mean(np.abs(steps - median) > IRREGULAR_STEP_FRACTION * median))
    status = WARN if share > WARN_IRREGULAR_SHARE else OK
    return Check("time_regularity", status, f"{share:.1%} of the time steps are irregular.")


def _check_loop(
    t_s: np.ndarray,
    columns: Mapping[str, np.ndarray],
    loop: LoopTags,
    cfg: ReadinessConfig,
) -> list[Check]:
    """A loop needs PV and SP (fail); OUT and MODE are needed for stiction and manual findings."""
    checks = _check_loop_roles(loop)
    for tag, role in _tags_with_roles(loop):
        if tag not in columns:
            # PV and SP are the minimum; a named OUT or MODE that is absent costs only findings
            status = FAIL if role in REQUIRED_ROLES else WARN
            checks.append(Check(f"tags:{loop.name}", status, f"Tag {tag} is not in the export."))
        else:
            values = np.asarray(columns[tag], dtype=float)
            checks.extend(_check_tag(t_s, values, tag, role in MOVING_ROLES, cfg))
    return checks


def _tags_with_roles(loop: LoopTags) -> list[tuple[str, str]]:
    """The loop's named tags as (tag, role) pairs; empty names are skipped."""
    roles = (("pv", loop.pv), ("sp", loop.sp), ("out", loop.out), ("mode", loop.mode))
    return [(tag, role) for role, tag in roles if tag]


def _check_loop_roles(loop: LoopTags) -> list[Check]:
    """Which of the four roles of a loop have a tag name at all."""
    name = f"tags:{loop.name}"
    checks = []
    if not loop.pv or not loop.sp:
        checks.append(Check(name, FAIL, f"Loop {loop.name} needs both a PV and an SP tag."))
    if not loop.out or not loop.mode:
        checks.append(
            Check(name, WARN, f"Loop {loop.name} has no OUT or MODE tag; stiction and manual "
                  "findings need them.")
        )
    return checks


def _check_tag(
    t_s: np.ndarray,
    values: np.ndarray,
    tag: str,
    can_be_stuck: bool,
    cfg: ReadinessConfig,
) -> list[Check]:
    """Missing values and, for tags that should move (PV, OUT), stuck stretches.

    A setpoint or a mode flag is constant for days in a healthy plant, so only PV and OUT are
    tested for being stuck.
    """
    checks = []
    missing = float(np.mean(np.isnan(values)))
    if missing > cfg.warn_missing_share:
        status = FAIL if missing > cfg.max_missing_share else WARN
        checks.append(Check(f"missing:{tag}", status, f"Tag {tag}: {missing:.1%} missing values."))
    flat = _flat_share(t_s, values) if can_be_stuck else 0.0
    if flat > cfg.warn_flat_share:
        status = FAIL if flat > cfg.max_flat_share else WARN
        checks.append(Check(f"flat:{tag}", status, f"Tag {tag}: {flat:.1%} of samples are stuck."))
    return checks


def _flat_share(t_s: np.ndarray, values: np.ndarray) -> float:
    """Share of samples in runs of identical values lasting at least 10 minutes (3 samples)."""
    period_s = float(np.median(np.diff(t_s)))
    run = max(MIN_FLAT_RUN_SAMPLES, int(FLAT_RUN_MINUTES * 60.0 / period_s))
    return float(flatline_fraction(values, run))
