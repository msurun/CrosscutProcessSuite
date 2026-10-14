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

# --- Thresholds (each pair: warn above / fail above) -------------------------

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
MIN_FLAT_RUN_SAMPLES = 3  # never fewer samples than this, so noise-free signals are not "flat"
SECONDS_PER_HOUR = 3600.0

REQUIRED_ROLES = ("pv", "sp")  # a missing tag of these roles fails the loop
MOVING_ROLES = ("pv", "out")  # signals that must vary; SP and MODE may sit still for days

OK, WARN, FAIL = "ok", "warn", "fail"


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
    t_s: np.ndarray, columns: Mapping[str, np.ndarray], loops: Sequence[LoopTags]
) -> ReadinessReport:
    """Check whether an export is good enough for loop monitoring and stiction detection.

    ``t_s`` are the timestamps in seconds, ``columns`` the series by tag name, ``loops`` the
    loops the customer wants analysed. The record needs at least two timestamps.
    """
    if len(t_s) < 2:
        return ReadinessReport((Check("duration", FAIL, "The record has fewer than 2 samples."),))
    time_checks = _check_time_steps(t_s)
    checks = [_check_duration(t_s), *time_checks]
    if any(check.status == FAIL for check in time_checks):
        return ReadinessReport(tuple(checks))  # the per-tag checks divide by the time step
    for loop in loops:
        checks.extend(_check_loop(t_s, columns, loop))
    return ReadinessReport(tuple(checks))


def _check_duration(t_s: np.ndarray) -> Check:
    """Fail below 6 h, warn below 24 h: a few oscillation cycles need hours of data."""
    hours = float(t_s[-1] - t_s[0]) / SECONDS_PER_HOUR
    if hours < MIN_DURATION_H:
        return Check("duration", FAIL, f"The record is {hours:.1f} h long; 6 h are needed.")
    if hours < WARN_DURATION_H:
        return Check("duration", WARN, f"The record is {hours:.1f} h long; 24 h is better.")
    return Check("duration", OK, f"The record is {hours:.1f} h long.")


def _check_time_steps(t_s: np.ndarray) -> list[Check]:
    """Sample period, regularity and ordering of the timestamps."""
    steps = np.diff(t_s)
    if not np.all(np.isfinite(t_s)) or np.any(steps <= 0):
        return [Check("time_order", FAIL, "Timestamps are missing, repeated or out of order.")]
    return [_check_period(float(np.median(steps))), _check_regularity(steps)]


def _check_period(period_s: float) -> Check:
    """Sample period: above 15 s hides valve stiction, above 60 s is too coarse."""
    if period_s > FAIL_PERIOD_S:
        return Check("sample_period", FAIL, f"Samples are {period_s:.0f} s apart; 60 s is max.")
    if period_s > STICTION_PERIOD_S:
        return Check(
            "sample_period",
            WARN,
            f"Samples are {period_s:.0f} s apart; slower than about 15 s hides valve stiction.",
        )
    return Check("sample_period", OK, f"Samples are {period_s:.1f} s apart.")


def _check_regularity(steps: np.ndarray) -> Check:
    """Share of time steps that differ from the median step by more than half of it."""
    median = float(np.median(steps))
    share = float(np.mean(np.abs(steps - median) > IRREGULAR_STEP_FRACTION * median))
    status = WARN if share > WARN_IRREGULAR_SHARE else OK
    return Check("time_regularity", status, f"{share:.1%} of the time steps are irregular.")


def _check_loop(
    t_s: np.ndarray, columns: Mapping[str, np.ndarray], loop: LoopTags
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
            checks.extend(_check_tag(t_s, values, tag, role in MOVING_ROLES))
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


def _check_tag(t_s: np.ndarray, values: np.ndarray, tag: str, can_be_stuck: bool) -> list[Check]:
    """Missing values and, for tags that should move (PV, OUT), stuck stretches.

    A setpoint or a mode flag is constant for days in a healthy plant, so only PV and OUT are
    tested for being stuck.
    """
    checks = []
    missing = float(np.mean(np.isnan(values)))
    if missing > WARN_NAN_SHARE:
        status = FAIL if missing > FAIL_NAN_SHARE else WARN
        checks.append(Check(f"missing:{tag}", status, f"Tag {tag}: {missing:.1%} missing values."))
    flat = _flat_share(t_s, values) if can_be_stuck else 0.0
    if flat > WARN_FLAT_SHARE:
        status = FAIL if flat > FAIL_FLAT_SHARE else WARN
        checks.append(Check(f"flat:{tag}", status, f"Tag {tag}: {flat:.1%} of samples are stuck."))
    return checks


def _flat_share(t_s: np.ndarray, values: np.ndarray) -> float:
    """Share of samples in runs of identical values lasting at least 10 minutes."""
    period_s = float(np.median(np.diff(t_s)))
    run = max(MIN_FLAT_RUN_SAMPLES, int(FLAT_RUN_MINUTES * 60.0 / period_s))
    return float(flatline_fraction(values, run))
