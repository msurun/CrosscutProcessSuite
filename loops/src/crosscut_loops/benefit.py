"""Estimate the economic benefit of reducing loop variability.

The estimate answers one question: if the standard deviation of a PV signal were
reduced by a given factor, how far could the process mean move towards its limit
before the limit margin is consumed again? The answer is expressed as a "shift"
in process units and, when a unit value is given, as money per hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_SAMPLES = 30  # below this count the mean and std are not trustworthy

SIDE_UPPER = "upper"
SIDE_LOWER = "lower"
VALID_SIDES = (SIDE_UPPER, SIDE_LOWER)

NOTE_BEYOND_LIMIT = "mean already beyond the limit"
NOTE_NEAR_LIMIT = "limit is already violated or nearly so at current variability"
NOTE_NO_VALUE = "no economic value given"


@dataclass(frozen=True)
class BenefitAssumptions:
    """Inputs that describe the limit, the tolerable margin and the money rate.

    Attributes:
        limit: Limit value of the PV signal, in signal units.
        side: ``"upper"`` or ``"lower"``; says on which side the limit sits.
        value_per_unit_h: Economic value of one unit of signal for one hour.
        margin_sigmas: Margin kept between the process mean and the limit, in
            standard deviations of the current signal.
        std_reduction: Fraction of the current standard deviation that is removed;
            the default ``0.5`` is read as the target being half of the current std.
    """

    limit: float
    side: str = SIDE_UPPER
    value_per_unit_h: float = 0.0
    margin_sigmas: float = 2.0
    std_reduction: float = 0.5


@dataclass(frozen=True)
class BenefitEstimate:
    """Result of the benefit estimation, all values in signal units or currency.

    Attributes:
        mean: Mean of the used samples.
        std_now: Standard deviation of the used samples.
        std_target: Standard deviation aimed for after the reduction.
        current_gap: Signed room between the mean and the limit; negative means
            the mean already sits beyond the limit.
        shift: Room the mean could move towards the limit, never negative.
        value_per_h: ``shift`` converted to money per hour, or ``0.0`` without value.
        n_samples_used: Number of finite samples that went into the statistics.
        notes: Warnings, in the order they were detected.
    """

    mean: float
    std_now: float
    std_target: float
    current_gap: float
    shift: float
    value_per_h: float
    n_samples_used: int
    notes: tuple[str, ...] = field(default_factory=tuple)


def estimate_benefit(pv: np.ndarray, assumptions: BenefitAssumptions) -> BenefitEstimate:
    """Estimate the benefit of reducing the variability of ``pv``.

    Returns a :class:`BenefitEstimate`. The input array is never modified.

    Raises:
        ValueError: if the assumptions are inconsistent or fewer than
            :data:`MIN_SAMPLES` finite samples are available.
    """
    _validate_assumptions(assumptions)
    samples = _finite_samples(pv)
    if samples.size < MIN_SAMPLES:
        raise ValueError(
            f"need at least {MIN_SAMPLES} finite samples to estimate a benefit, got {samples.size}"
        )

    mean = float(np.mean(samples))
    std_now = float(np.std(samples, ddof=1))
    std_target = std_now * (1.0 - assumptions.std_reduction)
    current_gap = _signed_gap(mean, assumptions)
    shift = _shift_towards_limit(current_gap, std_now, assumptions)
    value_per_h = shift * assumptions.value_per_unit_h

    return BenefitEstimate(
        mean=mean,
        std_now=std_now,
        std_target=std_target,
        current_gap=current_gap,
        shift=shift,
        value_per_h=value_per_h,
        n_samples_used=int(samples.size),
        notes=_build_notes(mean, current_gap, std_now, assumptions),
    )


def render_benefit_markdown(estimate: BenefitEstimate, assumptions: BenefitAssumptions) -> str:
    """Render a short markdown report of an estimate; every note is included."""
    lines = [
        "## Benefit estimate",
        "",
        "This number is an **estimate** based on the variability seen in the data.",
        "",
        f"- Samples used: {estimate.n_samples_used}",
        f"- Mean: {estimate.mean:.2f}",
        f"- Standard deviation now: {estimate.std_now:.2f}",
        f"- Standard deviation target: {estimate.std_target:.2f}",
        f"- Limit ({assumptions.side}): {assumptions.limit:.2f}",
        f"- Room to shift the mean: {estimate.shift:.2f}",
        f"- Value per hour: {estimate.value_per_h:.2f}",
    ]
    if estimate.notes:
        lines.append("")
        lines.extend(f"> {note}" for note in estimate.notes)
    return "\n".join(lines) + "\n"


def _validate_assumptions(assumptions: BenefitAssumptions) -> None:
    """Check the assumptions once, so the maths below can trust them."""
    if assumptions.side not in VALID_SIDES:
        raise ValueError(f"side must be one of {VALID_SIDES}, got {assumptions.side!r}")
    if not 0.0 <= assumptions.std_reduction < 1.0:
        raise ValueError(
            f"std_reduction must be in [0, 1), got {assumptions.std_reduction}"
        )
    if assumptions.margin_sigmas <= 0.0:
        raise ValueError(f"margin_sigmas must be positive, got {assumptions.margin_sigmas}")
    if assumptions.value_per_unit_h < 0.0:
        raise ValueError(
            f"value_per_unit_h must not be negative, got {assumptions.value_per_unit_h}"
        )


def _finite_samples(pv: np.ndarray) -> np.ndarray:
    """Return a copy of the finite samples of ``pv``; NaNs and infinities drop out."""
    samples = np.asarray(pv, dtype=float).ravel()
    return samples[np.isfinite(samples)].copy()


def _signed_gap(mean: float, assumptions: BenefitAssumptions) -> float:
    """Return the signed room between ``mean`` and the limit, in signal units.

    Positive means the mean is still on the safe side of the limit.
    """
    if assumptions.side == SIDE_UPPER:
        return assumptions.limit - mean
    return mean - assumptions.limit


def _shift_towards_limit(
    current_gap: float,
    std_now: float,
    assumptions: BenefitAssumptions,
) -> float:
    """Return how far the mean could move towards the limit without breaking the margin.

    In plain words: with the shrunk spread, the mean may sit ``margin_sigmas``
    target standard deviations away from the limit. The room gained by shrinking
    the spread is the margin in sigmas times the standard deviation that was
    removed; it is capped at the room available today and never negative.
    """
    freed_room = assumptions.margin_sigmas * std_now * assumptions.std_reduction
    return max(0.0, min(freed_room, current_gap))


def _build_notes(
    mean: float,
    current_gap: float,
    std_now: float,
    assumptions: BenefitAssumptions,
) -> tuple[str, ...]:
    """Collect the warnings that apply to this estimate."""
    notes: list[str] = []
    if current_gap <= 0.0:
        notes.append(NOTE_BEYOND_LIMIT)
    elif current_gap < assumptions.margin_sigmas * std_now:
        notes.append(NOTE_NEAR_LIMIT)
    if assumptions.value_per_unit_h == 0.0:
        notes.append(NOTE_NO_VALUE)
    return tuple(notes)
