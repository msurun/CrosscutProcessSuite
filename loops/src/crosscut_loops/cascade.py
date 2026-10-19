"""Series cascade control planning for two nested PI loops.

In a series cascade the slow variable y1 (for example a reactor temperature) is held
by a master controller whose output is the setpoint of a fast inner loop; that inner
loop holds y2 (for example the jacket temperature) by moving the valve u2. The inner
loop absorbs the fast disturbances, so the outer loop sees a much friendlier process.

Tune the loops in order. First close and tune the inner (slave) loop alone. Then
identify the outer process from the inner SETPOINT to y1 with the inner loop already
closed, and tune the outer loop on that identified model. With SIMC tuning the inner loop
then looks, from the outside, like T2 = exp(-theta2 s)/(tau_c2 s + 1): a first-order lag of
its closed-loop time constant tau_c2 plus its dead time theta2.

Separate the two time scales: sigma = tau_c1 / tau_c2 should be 4 to 10. Below 4 the
loops fight each other (the inner loop has only converged 98 % after 4 tau_c2); 10 is
the recommended value (Shinskey 1981; Skogestad, NTNU lecture APC6 "Standard control
elements / cascade", pages 12-15). If you cannot reach 4, speed up the inner loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crosscut_loops.tuning_rules import FopdtModel, PiSettings, simc_pi

# Lowest acceptable ratio tau_c_outer / tau_c_inner, after Shinskey (1981, p. 12), see
# docs/PROVENANCE.md.
# A first-order inner loop has reached 98 % of its setpoint after 4 tau_c2, so an
# outer loop faster than that would chase a setpoint the inner loop cannot follow.
MIN_SEPARATION = 4.0

# Recommended ratio tau_c_outer / tau_c_inner (Skogestad, lecture APC6).
RECOMMENDED_SEPARATION = 10.0

# Separation above this multiple of the recommended value means the outer loop has
# been slowed down instead of the inner loop being sped up. Slowing the outer loop
# throws away the disturbance rejection the cascade was built for.
_MAX_SEPARATION_FACTOR = 2.0


@dataclass(frozen=True)
class CascadePlan:
    """A tuned cascade: settings for both loops and the resulting separation.

    Attributes:
        inner: PI settings for the slave loop (u2 -> y2).
        outer: PI settings for the master loop (inner setpoint -> y1).
        tau_c_inner_s: Closed-loop time constant of the inner loop, in seconds.
        tau_c_outer_s: Closed-loop time constant of the outer loop, in seconds.
        separation: Achieved ratio tau_c_outer_s / tau_c_inner_s.
        warnings: Human-readable remarks about the tuning, empty when all is well.
        order: The order the loops must be commissioned in: inner first.
    """

    inner: PiSettings
    outer: PiSettings
    tau_c_inner_s: float
    tau_c_outer_s: float
    separation: float
    warnings: tuple[str, ...] = field(default_factory=tuple)
    order: tuple[str, str] = ("inner", "outer")


def time_scale_separation(tau_c_inner_s: float, tau_c_outer_s: float) -> float:
    """Return the cascade separation sigma = tau_c_outer / tau_c_inner.

    Args:
        tau_c_inner_s: Closed-loop time constant of the inner loop, in seconds.
        tau_c_outer_s: Closed-loop time constant of the outer loop, in seconds.

    Returns:
        The dimensionless ratio tau_c_outer_s / tau_c_inner_s.

    Raises:
        ValueError: If either time constant is not positive.
    """
    if tau_c_inner_s <= 0.0:
        raise ValueError("Inner closed-loop time constant tau_c must be positive")
    if tau_c_outer_s <= 0.0:
        raise ValueError("Outer closed-loop time constant tau_c must be positive")
    return tau_c_outer_s / tau_c_inner_s


def _separation_warnings(requested: float, achieved: float) -> tuple[str, ...]:
    """Collect the warnings for a requested and an achieved separation."""
    warnings: list[str] = []
    if requested < MIN_SEPARATION:
        warnings.append(
            f"requested separation {requested:g} is below {MIN_SEPARATION:g}: "
            "the loops may interact (Shinskey 1981)"
        )
    if achieved < MIN_SEPARATION:
        warnings.append(
            f"achieved separation {achieved:g} is below {MIN_SEPARATION:g}: "
            "tune the inner loop tighter or accept the interaction"
        )
    if achieved > _MAX_SEPARATION_FACTOR * RECOMMENDED_SEPARATION:
        warnings.append(
            f"the outer loop is slow: separation {achieved:g} exceeds "
            f"{_MAX_SEPARATION_FACTOR * RECOMMENDED_SEPARATION:g}; tune the inner loop "
            "tighter instead of slowing the outer (Skogestad: the time window shrinks "
            "with every layer)"
        )
    return tuple(warnings)


def plan_cascade(
    inner: FopdtModel,
    outer: FopdtModel,
    separation: float = RECOMMENDED_SEPARATION,
) -> CascadePlan:
    """Tune both loops of a series cascade with SIMC and report the separation.

    Tuning order matters: the inner loop is tuned first and then closed, and the
    outer model is identified from the inner setpoint to y1 with that loop closed.

    Args:
        inner: FOPDT model of the slave loop, from u2 to y2.
        outer: FOPDT model of the master loop, from the inner setpoint to y1,
            identified with the inner loop closed.
        separation: Requested ratio tau_c_outer / tau_c_inner. Defaults to
            RECOMMENDED_SEPARATION.

    Returns:
        CascadePlan with both sets of PI settings, the achieved separation and any
        warnings.

    Raises:
        ValueError: If separation is not positive.
    """
    if separation <= 0.0:
        raise ValueError("Separation must be positive")

    # SIMC's tight-control choice is tau_c = theta (the loop's own delay). The inner
    # loop is the fast one, so it gets this tightest recommended setting.
    tau_c_inner_s = inner.delay_s
    inner_settings = simc_pi(inner, tau_c_inner_s)

    # The outer loop must stay at least `separation` times slower than the inner loop,
    # and never faster than tight control of the outer process alone would allow
    # (tau_c = the outer delay). The max() keeps both constraints.
    tau_c_outer_s = max(separation * tau_c_inner_s, outer.delay_s)
    outer_settings = simc_pi(outer, tau_c_outer_s)

    # The achieved ratio can differ from the request, because the outer delay may have
    # pushed tau_c_outer_s above separation * tau_c_inner_s.
    achieved = time_scale_separation(tau_c_inner_s, tau_c_outer_s)
    return CascadePlan(
        inner=inner_settings,
        outer=outer_settings,
        tau_c_inner_s=tau_c_inner_s,
        tau_c_outer_s=tau_c_outer_s,
        separation=achieved,
        warnings=_separation_warnings(separation, achieved),
    )
