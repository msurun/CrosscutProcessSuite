"""Tests for the timing-fault helpers: timestamp jitter and loop-mode flips.

Jitter must stay deterministic, sorted and bounded; flips must turn into a valid
event schedule that a recorder can feed to a plant.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_sim.core import AUTO, CAS, MAN, Event
from crosscut_sim.dataset import Samples
from crosscut_sim.timing_faults import ModeFlip, jitter_samples, jitter_timestamps, mode_flip_events

# NS_PER_S: nanoseconds in one second, the unit bridge between the jitter API in
# seconds and the int64 nanosecond timestamps it operates on.
NS_PER_S = 10**9
INVALID_MODE = 7  # not one of MAN, AUTO, CAS
GRID_START_NS = 1_700_000_000 * NS_PER_S


def sample_grid(count: int, spacing_s: float = 1.0) -> np.ndarray:
    """Return ``count`` strictly increasing int64 timestamps, ``spacing_s`` seconds apart."""
    offsets_ns = np.arange(count, dtype=np.int64) * round(spacing_s * NS_PER_S)
    return (GRID_START_NS + offsets_ns).astype(np.int64)


def tiny_samples() -> Samples:
    """Return a 5x2 Samples fixture: 2 tags, 5 timestamps, distinct values and qualities."""
    ts_ns = sample_grid(5, spacing_s=2.0)
    values = np.arange(10, dtype=np.float64).reshape(5, 2)
    qualities = np.array([[0, 1], [1, 2], [2, 0], [0, 1], [1, 2]], dtype=np.uint8)
    return Samples(ts_ns, ["a", "b"], values, qualities)


def test_the_same_seed_produces_the_same_timestamps() -> None:
    ts_ns = sample_grid(500)
    assert np.array_equal(jitter_timestamps(ts_ns, 5.0, 7), jitter_timestamps(ts_ns, 5.0, 7))


def test_a_different_seed_produces_different_timestamps() -> None:
    ts_ns = sample_grid(500)
    assert not np.array_equal(jitter_timestamps(ts_ns, 5.0, 7), jitter_timestamps(ts_ns, 5.0, 8))


def test_output_stays_strictly_increasing_on_a_one_second_grid() -> None:
    ts_ns = jitter_timestamps(sample_grid(1000), sigma_s=5.0, seed=3)
    assert np.all(np.diff(ts_ns) > 0)


def test_sample_order_is_preserved_by_the_jitter() -> None:
    ts_ns = sample_grid(1000)
    jittered = jitter_timestamps(ts_ns, sigma_s=5.0, seed=3)
    # Ranking recovered with argsort: sorted positions must give back the input order.
    assert np.array_equal(np.argsort(np.argsort(jittered)), np.arange(len(ts_ns)))


def test_offset_never_exceeds_three_sigma_on_a_sparse_grid() -> None:
    sigma_s = 5.0
    ts_ns = sample_grid(1000, spacing_s=60.0)
    offset_ns = np.abs(jitter_timestamps(ts_ns, sigma_s, 11) - ts_ns)
    # Tolerance covers the 1 ns cumulative fix that keeps neighbours apart.
    assert offset_ns.max() <= 3 * sigma_s * NS_PER_S + len(ts_ns)


def test_zero_sigma_returns_an_equal_copy() -> None:
    ts_ns = sample_grid(20)
    jittered = jitter_timestamps(ts_ns, sigma_s=0.0, seed=1)
    assert np.array_equal(jittered, ts_ns)
    assert jittered is not ts_ns


def test_negative_sigma_is_rejected() -> None:
    with pytest.raises(ValueError, match="sigma"):
        jitter_timestamps(sample_grid(5), sigma_s=-0.1, seed=1)


def test_timestamps_that_are_not_strictly_increasing_are_rejected() -> None:
    ts_ns = np.array([0, 5, 5, 9], dtype=np.int64)
    with pytest.raises(ValueError, match="increasing"):
        jitter_timestamps(ts_ns, sigma_s=1.0, seed=1)


def test_jitter_samples_keeps_values_qualities_and_tag_ids() -> None:
    samples = tiny_samples()
    jittered = jitter_samples(samples, sigma_s=2.0, seed=4)
    assert jittered.tag_ids == samples.tag_ids
    assert np.array_equal(jittered.values, samples.values)
    assert np.array_equal(jittered.qualities, samples.qualities)


def test_jitter_samples_changes_only_the_timestamps() -> None:
    samples = tiny_samples()
    jittered = jitter_samples(samples, sigma_s=2.0, seed=4)
    assert np.array_equal(jittered.ts_ns, jitter_timestamps(samples.ts_ns, 2.0, 4))


def test_mode_flip_rejects_a_negative_start() -> None:
    with pytest.raises(ValueError, match="start_s"):
        ModeFlip(start_s=-1.0, duration_s=60.0)


def test_mode_flip_rejects_a_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="duration_s"):
        ModeFlip(start_s=0.0, duration_s=0.0)


def test_mode_flip_rejects_an_unknown_target_mode() -> None:
    with pytest.raises(ValueError, match="to_mode"):
        ModeFlip(start_s=0.0, duration_s=60.0, to_mode=99)


def test_a_flip_becomes_a_start_event_and_a_return_event() -> None:
    events = mode_flip_events("loop.mode", [ModeFlip(start_s=10.0, duration_s=30.0)])
    assert events == (Event(10.0, "loop.mode", MAN), Event(40.0, "loop.mode", AUTO))


def test_two_flips_come_out_sorted_with_their_own_values() -> None:
    flips = [
        ModeFlip(start_s=100.0, duration_s=20.0, to_mode=MAN),
        ModeFlip(start_s=10.0, duration_s=5.0, to_mode=CAS),
    ]
    events = mode_flip_events("loop.mode", flips)
    assert [event.t_s for event in events] == [10.0, 15.0, 100.0, 120.0]
    assert [event.value for event in events] == [CAS, AUTO, MAN, AUTO]


def test_flips_that_touch_are_allowed() -> None:
    flips = [
        ModeFlip(start_s=0.0, duration_s=10.0),
        ModeFlip(start_s=10.0, duration_s=10.0, to_mode=CAS),
    ]
    assert len(mode_flip_events("loop.mode", flips)) == 4


def test_overlapping_flips_are_rejected() -> None:
    flips = [
        ModeFlip(start_s=0.0, duration_s=10.0),
        ModeFlip(start_s=9.0, duration_s=10.0),
    ]
    with pytest.raises(ValueError, match="overlap"):
        mode_flip_events("loop.mode", flips)


def test_an_invalid_return_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="return_mode"):
        mode_flip_events("loop.mode", [ModeFlip(0.0, 10.0)], return_mode=INVALID_MODE)


def test_jittered_timestamps_stay_int64_and_strictly_increasing_at_epoch_scale() -> None:
    ts_ns = (1_760_000_000 * NS_PER_S + np.arange(100, dtype=np.int64) * NS_PER_S).astype(np.int64)
    jittered = jitter_timestamps(ts_ns, 0.01, seed=1)
    assert jittered.dtype == np.int64
    assert np.all(np.diff(jittered) > 0)


def test_a_flip_can_hand_the_loop_back_to_cascade() -> None:
    flips = [ModeFlip(start_s=10.0, duration_s=30.0, return_to=CAS)]
    events = mode_flip_events("loop.mode", flips)
    assert events == (Event(10.0, "loop.mode", MAN), Event(40.0, "loop.mode", CAS))


def test_an_invalid_return_to_is_rejected() -> None:
    with pytest.raises(ValueError, match="return_to"):
        ModeFlip(start_s=0.0, duration_s=1.0, return_to=INVALID_MODE)
