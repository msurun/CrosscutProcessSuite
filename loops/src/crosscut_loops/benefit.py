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

    The model is "shrink the spread, gain the headroom": variability (the standard
    deviation of ``pv``) is assumed to be reducible by a fixed fraction, and the
    resulting tightening of the process is turned into money at a fixed rate.

    Returns a :class:`BenefitEstimate`. The input array is never modified.

    Raises:
        ValueError: if the assumptions are inconsistent or fewer than
            :data:`MIN_SAMPLES` finite samples are available.
    """
    # Fail fast on nonsense assumptions (e.g. a negative reduction fraction) so the
    # arithmetic below is guaranteed to produce a physically meaningful estimate.
    _validate_assumptions(assumptions)

    # Work on a copy of the finite samples only: NaNs and infinities would poison
    # the mean and the standard deviation, and the caller's array must stay untouched.
    samples = _finite_samples(pv)

    # A spread estimated from too few points is noise, not signal, so refuse to guess.
    if samples.size < MIN_SAMPLES:
        raise ValueError(
            f"need at least {MIN_SAMPLES} finite samples to estimate a benefit, got {samples.size}"
        )

    mean = float(np.mean(samples))

    # ddof=1 gives the sample (Bessel-corrected) standard deviation: we are estimating
    # the spread of an underlying process from a finite sample, not describing the sample
    # itself. Both mean and std_now are in the same unit as ``pv``.
    std_now = float(np.std(samples, ddof=1))

    # The post-improvement spread: reduce the current spread by the assumed fraction
    # (``std_reduction`` is a dimensionless ratio in [0, 1), so 0.1 means "10% tighter").
    std_target = std_now * (1.0 - assumptions.std_reduction)

    # How far the current mean sits from the limit we care about, signed: positive means
    # the mean is on the safe side and has room to move, negative means it is already over.
    current_gap = _signed_gap(mean, assumptions)

    # How much of that gap the tightened spread is assumed to buy back, in the unit of
    # ``pv``. This is the single quantity the whole model turns on.
    shift = _shift_towards_limit(current_gap, std_now, assumptions)

    # Turn the physical shift into money: ``value_per_unit_h`` is currency per (unit of
    # ``pv`` x hour), so a shift expressed in units per hour yields currency per hour.
    value_per_h = shift * assumptions.value_per_unit_h

    # ``n_samples_used`` is reported alongside the figures so a reader can judge how much
    # of the estimate is driven by the assumption set versus by the evidence in ``pv``.
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
    """Render a short markdown report of an estimate; every note is included.

    Pure formatting: takes an already computed `BenefitEstimate` (the statistics) and the
    `BenefitAssumptions` it was computed under (the specification limits and the side of the
    distribution we care about) and turns them into a markdown string ending in a newline.
    It raises nothing and reads no global state; the two inputs carry everything it needs.
    """
    # Markdown document assembled line by line, then joined at the end. Building a list and
    # joining once avoids a quadratic string concatenation and keeps the layout readable.
    lines = [
        "## Benefit estimate",
        "",
        "This number is an **estimate** based on the variability seen in the data.",
        "",
        # `n_samples_used` is a count (unit: samples), so it gets no decimal formatting.
        # `mean`, `std_now`, `std_target`, `limit`, `shift` and `value_per_h` are all in the
        # same physical unit as the measured quantity; `value_per_h` is that unit per hour
        # (unit: value/hour). All of them use .2f, i.e. two decimals, for a stable column width.
        f"- Samples used: {estimate.n_samples_used}",
        f"- Mean: {estimate.mean:.2f}",
        f"- Standard deviation now: {estimate.std_now:.2f}",
        f"- Standard deviation target: {estimate.std_target:.2f}",
        f"- Limit ({assumptions.side}): {assumptions.limit:.2f}",
        f"- Room to shift the mean: {estimate.shift:.2f}",
        f"- Value per hour: {estimate.value_per_h:.2f}",
    ]
    # `notes` is a sequence of free-text warnings produced during the estimate. Rendering them
    # as markdown blockquotes (a "> " prefix per line) sets them apart from the bullet list.
    # The guard keeps the report free of a trailing empty line when there are no notes.
    if estimate.notes:
        lines.append("")
        lines.extend(f"> {note}" for note in estimate.notes)
    return "\n".join(lines) + "\n"


def _validate_assumptions(assumptions: BenefitAssumptions) -> None:
    """Check the assumptions once, so the maths below can trust them.

    This is a guard clause: it only raises. Downstream code applies a normal
    distribution and a multiplicative reduction, and both would silently return
    nonsense (a negative sigma, a division by zero) instead of failing, so every
    domain rule is asserted here.

    Raises:
        ValueError: if any field of ``assumptions`` is outside its valid range.
    """
    # "side" decides which tail of the distribution counts as a benefit and is
    # therefore restricted to a fixed vocabulary of known labels.
    if assumptions.side not in VALID_SIDES:
        raise ValueError(f"side must be one of {VALID_SIDES}, got {assumptions.side!r}")
    # Relative reduction of the standard deviation, unitless. An exclusive upper
    # bound of 1.0 keeps the post-reduction sigma strictly positive, and the lower
    # bound of 0.0 forbids a growth of the spread (which the model does not model).
    if not 0.0 <= assumptions.std_reduction < 1.0:
        raise ValueError(
            f"std_reduction must be in [0, 1), got {assumptions.std_reduction}"
        )
    # Safety margin expressed in units of the (remaining) standard deviation,
    # unitless. It multiplies sigma, so a zero or negative value would collapse or
    # flip the margin.
    if assumptions.margin_sigmas <= 0.0:
        raise ValueError(f"margin_sigmas must be positive, got {assumptions.margin_sigmas}")
    # Monetary worth of one unit of benefit per hour, in currency per unit-hour.
    # Zero is allowed (a benefit worth nothing), a negative price is not.
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

    "Signal units" means the unit of the measured signal itself (for example
    millimeters or grams), not a probability and not a percentage.

    ``assumptions.side`` says which direction counts as safe:

    * ``SIDE_UPPER``: the limit is a ceiling, so the mean must stay *below* it
      and the gap is ``limit - mean``.
    * anything else (the lower side): the limit is a floor, so the mean must
      stay *above* it and the gap is ``mean - limit``.

    Returns:
        The distance to the limit, in signal units. A positive value means the
        mean is inside the allowed range; zero means it sits exactly on the
        limit; a negative value means the mean is already offside. The
        magnitude is how much slack is left (or how far the excess goes).
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

    Model: the limit is a regulatory or business ceiling on a metric, and the
    margin is the safety buffer kept between the mean and that limit. The buffer
    is expressed in standard deviations of the metric (``margin_sigmas``), so the
    mean is allowed to sit that many sigmas away from the limit.

    Shrinking the spread (multiplying the standard deviation by
    ``std_reduction``) removes spread that used to consume part of the margin,
    which frees the same number of sigmas worth of distance for the mean to use.

    In plain words: with the shrunk spread, the mean may sit ``margin_sigmas``
    target standard deviations away from the limit. The room gained by shrinking
    the spread is the margin in sigmas times the standard deviation that was
    removed; it is capped at the room available today and never negative.

    Parameters
    ----------
    current_gap : float
        Distance available today between the mean and the limit, in metric units.
    std_now : float
        Current standard deviation of the metric, in metric units.
    assumptions : BenefitAssumptions
        Holds ``margin_sigmas`` (buffer width, dimensionless count of sigmas) and
        ``std_reduction`` (fraction of the standard deviation removed, 0.0 to 1.0).

    Returns
    -------
    float
        Room the mean may move towards the limit, in metric units. Non-negative
        and never larger than ``current_gap``.
    """
    # Room freed by the shrink = (sigmas of margin) * (std removed).
    # Derivation: margin_sigmas * std_now is the current buffer in metric units;
    # multiplying by std_reduction keeps only the part of it that the smaller spread gives back.
    freed_room = assumptions.margin_sigmas * std_now * assumptions.std_reduction
    # Clamp to [0, current_gap]: the mean cannot move backwards (0.0 floor) and
    # cannot pass the limit, so the cap is the distance still available today.
    return max(0.0, min(freed_room, current_gap))


def _build_notes(
    mean: float,
    current_gap: float,
    std_now: float,
    assumptions: BenefitAssumptions,
) -> tuple[str, ...]:
    """Collect the warnings that apply to this estimate.

    These notes are short machine-readable codes the UI turns into sentences,
    so the caller can explain a low or uncertain benefit to the user.

    The estimate is a normal distribution of benefit value: ``mean`` is its
    expected value (the point estimate) in the benefit currency, and
    ``std_now`` is the uncertainty (standard deviation) of that estimate.

    Args:
        mean: Expected benefit of acting now, in the benefit currency. Used by
            the caller for display; no note depends on it here.
        current_gap: Distance from the operating limit, in the same unit as
            ``mean``. Zero or negative means the limit has been crossed.
        std_now: Standard deviation of the benefit estimate, in the same unit.
            Used as the yardstick for "how close is close".
        assumptions: Tunables of the benefit model. ``margin_sigmas`` is a count
            of standard deviations; ``value_per_unit_h`` is currency per hour.

    Returns:
        Warning codes, in the order they are appended; may be empty.
    """
    notes: list[str] = []

    # "Near the limit" is judged in units of the estimate's own uncertainty:
    # a gap smaller than margin_sigmas standard deviations could easily flip
    # sign, so we flag it. Zero gap or less is already past the limit, which
    # subsumes the near case, hence the if/elif rather than two ifs.
    if current_gap <= 0.0:
        notes.append(NOTE_BEYOND_LIMIT)
    elif current_gap < assumptions.margin_sigmas * std_now:
        notes.append(NOTE_NEAR_LIMIT)

    # A per-hour value of exactly zero means the model was configured with no
    # way to price the benefit, so any estimate above is unpriceable.
    if assumptions.value_per_unit_h == 0.0:
        notes.append(NOTE_NO_VALUE)

    # Tuple, not list: callers store and compare these as an immutable summary.
    return tuple(notes)
