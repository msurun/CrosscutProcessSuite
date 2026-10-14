"""Faults the read-path wrapper cannot express: sample timestamp jitter and mode flips.

``faults.py`` corrupts values and quality codes while a client reads a snapshot. It cannot
touch the timestamp a historian already recorded, nor change an operator mode as a scheduled
scenario event. This module adds both: jitter is applied offline to a recorded dataset, and a
mode flip is turned into ordinary write events that any plant replays at step time.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from crosscut_sim.core import AUTO, CAS, MAN, Event
from crosscut_sim.dataset import Samples

# Smallest allowed distance between two jittered stamps, in nanoseconds. Arrival order must be
# preserved: two samples stamped at the same nanosecond, or out of order, break any consumer that
# assumes a strictly increasing time index (resampling, joins, rate-of-change calculations).
MIN_GAP_NS = 1

# Arrival delays are clipped at this many standard deviations because a normal draw is unbounded
# and a single tail sample could otherwise move a stamp by minutes, outside any plausible latency.
MAX_DELAY_SIGMA = 3.0

# Fixed tag mixed into the seed so the jitter stream is reproducible yet differs from any other
# random stream the caller starts from the same episode seed.
JITTER_SEED_TAG = 0x717E

# The mode tag carries the mode code as a float, matching the MODE tag convention of core.py.
VALID_MODES = (MAN, AUTO, CAS)


def jitter_timestamps(ts_ns: np.ndarray, sigma_s: float, seed: int) -> np.ndarray:
    """Return ``ts_ns`` perturbed by a random arrival delay of standard deviation ``sigma_s``.

    Model: a historian stamps a sample when it *arrives*, so the recorded instant is the true
    instant plus a network/queue delay. Delays are independent normal draws in seconds, clipped
    to ``+-3 * sigma_s``, and then repaired so the output is still strictly increasing with a
    minimum spacing of ``MIN_GAP_NS`` nanoseconds.

    Args:
        ts_ns: Sample instants in nanoseconds since the Unix epoch, int64, sorted ascending and
            strictly increasing. The input array is never modified.
        sigma_s: Standard deviation of the arrival delay, in seconds. ``0`` returns an exact copy.
        seed: Seed for the jitter generator; the same seed yields the same jitter.

    Returns:
        A new int64 array of the same length, strictly increasing.

    Raises:
        ValueError: If ``sigma_s`` is negative, if ``ts_ns`` is empty, or if ``ts_ns`` is not
            strictly increasing.
    """
    if sigma_s < 0:
        raise ValueError("sigma_s must be non-negative")
    if ts_ns.size == 0:
        raise ValueError("ts_ns must contain at least one timestamp")
    if np.any(np.diff(ts_ns) <= 0):
        raise ValueError("ts_ns must be sorted and strictly increasing")
    if sigma_s == 0:
        return ts_ns.copy()

    offsets_ns = _draw_delays_ns(ts_ns.size, sigma_s, seed)
    # Offsets can be negative (a sample stamped slightly early) and may reorder neighbours, so
    # sort the perturbed stamps before repairing the spacing.
    return _enforce_min_gap(np.sort(ts_ns.astype(np.int64) + offsets_ns))


def _draw_delays_ns(sample_count: int, sigma_s: float, seed: int) -> np.ndarray:
    """Return ``sample_count`` independent arrival delays in nanoseconds.

    Pure draw, no state: the delay is normal with mean zero and standard deviation ``sigma_s``
    seconds, clipped to ``+-3 * sigma_s`` and rounded to whole nanoseconds.
    """
    rng = np.random.default_rng([seed, JITTER_SEED_TAG])
    sigma_ns = sigma_s * 1e9  # convert seconds to nanoseconds
    delays_ns = rng.normal(loc=0.0, scale=sigma_ns, size=sample_count)
    clipped_ns = np.clip(delays_ns, -MAX_DELAY_SIGMA * sigma_ns, MAX_DELAY_SIGMA * sigma_ns)
    # int64 on purpose: adding float64 offsets to nanosecond stamps (about 1.8e18) would turn the
    # sum into float64, whose spacing there is 256 ns, and the 1 ns minimum gap could not exist.
    return np.rint(clipped_ns).astype(np.int64)


def _enforce_min_gap(sorted_ts_ns: np.ndarray) -> np.ndarray:
    """Return ``sorted_ts_ns`` pushed apart so consecutive stamps differ by at least MIN_GAP_NS.

    Cumulative-maximum trick: index ``k`` subtracts ``k * MIN_GAP_NS``, takes the running maximum
    over the prefix, and adds ``k * MIN_GAP_NS`` back. The subtraction maps "gap of at least
    MIN_GAP_NS" to "non-decreasing", ``maximum.accumulate`` makes the sequence non-decreasing
    without ever moving a stamp earlier than its input, and the addition restores the gap. Input
    must already be sorted ascending.
    """
    gaps = np.arange(sorted_ts_ns.size, dtype=np.int64) * MIN_GAP_NS
    return np.maximum.accumulate(sorted_ts_ns - gaps) + gaps


def jitter_samples(samples: Samples, sigma_s: float, seed: int) -> Samples:
    """Return ``samples`` with jittered timestamps and every other field unchanged.

    WHY the values stay put: a sample is a measurement of one physical instant, and that instant
    is what the value means. Only the historian's stamp of *when it was received* is wrong, so the
    value keeps its nominal instant and only ``ts_ns`` is rewritten.

    Args:
        samples: Recorded dataset batch; ``ts_ns`` must be int64 nanoseconds, sorted ascending.
        sigma_s: Standard deviation of the arrival delay, in seconds.
        seed: Seed for the jitter generator.

    Returns:
        A new ``Samples`` with the jittered ``ts_ns``; the original is untouched.

    Raises:
        ValueError: If ``sigma_s`` is negative or ``samples.ts_ns`` is not strictly increasing.
    """
    jittered_ts_ns = jitter_timestamps(samples.ts_ns, sigma_s, seed)
    return dataclasses.replace(samples, ts_ns=jittered_ts_ns)


@dataclass(frozen=True)
class ModeFlip:
    """A scheduled operator mode change: hold ``to_mode`` for ``duration_s`` seconds.

    Models an operator who takes a loop off automatic and hands it back later: the plant is
    written ``to_mode`` at ``start_s`` and written ``return_to`` (default: the ``return_mode`` of
    :func:`mode_flip_events`, AUTO) at ``start_s + duration_s``. Give ``return_to=CAS`` for a loop
    that ran in cascade before the flip. Times are seconds from the start of the episode.

    Raises:
        ValueError: If ``start_s`` is negative, ``duration_s`` is not positive, or ``to_mode``
            is not one of ``MAN``, ``AUTO``, ``CAS``.
    """

    start_s: float
    duration_s: float
    to_mode: int = MAN
    return_to: int | None = None

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise ValueError("start_s must be non-negative")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if self.to_mode not in VALID_MODES:
            raise ValueError(f"to_mode must be one of {VALID_MODES}, got {self.to_mode}")
        if self.return_to is not None and self.return_to not in VALID_MODES:
            raise ValueError(f"return_to must be one of {VALID_MODES}, got {self.return_to}")


def mode_flip_events(
    mode_tag: str,
    flips: Sequence[ModeFlip],
    return_mode: int = AUTO,
) -> tuple[Event, ...]:
    """Return the write events that replay ``flips`` on ``mode_tag``.

    Each flip becomes two events: one that writes ``float(flip.to_mode)`` at ``flip.start_s``
    and one that writes ``float(return_mode)`` at ``flip.start_s + flip.duration_s``. The mode
    tag is a numeric tag whose value is the mode code, so the codes are written as floats.

    Flips are sorted by start time first, which also makes the overlap check a single pass over
    the previous end. Overlap is rejected instead of resolved because two flips touching the same
    tag would fight over its value and make the run depend on list order.

    Args:
        mode_tag: Tag id of the loop mode, e.g. ``"line1.loop1.MODE"``.
        flips: Mode changes for this tag; their order in the sequence is irrelevant.
        return_mode: Mode written when a flip ends. Defaults to ``AUTO``.

    Returns:
        Write events sorted by ``t_s``.

    Raises:
        ValueError: If ``return_mode`` is not a valid mode, or if two flips overlap in time.
    """
    if return_mode not in VALID_MODES:
        raise ValueError(f"return_mode must be one of {VALID_MODES}, got {return_mode}")
    ordered_flips = sorted(flips, key=lambda flip: flip.start_s)
    _check_no_overlap(ordered_flips)
    events: list[Event] = []
    for flip in ordered_flips:
        # The mode the loop runs in during the flip belongs to the flip's own window; the
        # hand-back event is one duration later, so the window is [start_s, start_s + duration_s).
        events.append(Event(flip.start_s, mode_tag, float(flip.to_mode)))
        back = return_mode if flip.return_to is None else flip.return_to
        events.append(Event(flip.start_s + flip.duration_s, mode_tag, float(back)))
    return tuple(sorted(events, key=lambda event: event.t_s))


def _check_no_overlap(ordered_flips: Sequence[ModeFlip]) -> None:
    """Raise ``ValueError`` if two flips of ``ordered_flips`` share a moment in time.

    ``ordered_flips`` must already be sorted by ``start_s``; each flip is compared with its
    predecessor, which is enough to detect every overlap on a single axis.
    """
    for previous, current in zip(ordered_flips, ordered_flips[1:], strict=False):
        previous_end_s = previous.start_s + previous.duration_s
        if current.start_s < previous_end_s:
            raise ValueError(
                f"mode flips overlap: flip at {current.start_s}s starts before "
                f"{previous_end_s}s"
            )
