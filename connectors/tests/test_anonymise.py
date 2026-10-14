"""Behaviour tests for crosscut_connectors.anonymise.

They pin down the sharing contract: tags are renamed in input order, grouped and
kept tags keep their meaning, scales and time are hidden, NaN and sample spacing
survive, and the transform recipe can be inverted. The same seed must reproduce
the same export, or a third party could not compare two runs.
"""

from __future__ import annotations

import numpy as np
import pytest
from crosscut_connectors.anonymise import (
    OFFSET_FALLBACK,
    SCALE_LOG_MAX,
    SCALE_LOG_MIN,
    AnonymisedData,
    anonymise,
    invert_values,
)

SAMPLE_COUNT = 200
SAMPLE_PERIOD_S = 10.0


def _sample_time() -> np.ndarray:
    """Return a 200-sample time vector, 10 s apart, starting at 0 s."""
    return np.arange(SAMPLE_COUNT) * SAMPLE_PERIOD_S


def _sample_columns() -> dict[str, np.ndarray]:
    """Return two realistic signals: a sine-like measurement and a ramp setpoint."""
    t_s = _sample_time()
    return {
        "pv": np.sin(t_s / 50.0),
        "sp": 0.9 * np.sin(t_s / 50.0) + 0.5,
    }


def test_names_become_sequential_tags_in_input_order() -> None:
    """The i-th input column becomes tag_{i+1:03d}, and tag_map says which is which."""
    data = anonymise(_sample_time(), _sample_columns(), seed=1)

    assert list(data.columns) == ["tag_001", "tag_002"]
    assert data.tag_map == {"pv": "tag_001", "sp": "tag_002"}


def test_a_linked_group_shares_one_transform() -> None:
    """A shared (scale, offset) keeps the row-wise difference sp - pv proportional."""
    data = anonymise(_sample_time(), _sample_columns(), linked_groups=[["pv", "sp"]], seed=2)

    assert data.transforms["tag_001"] == data.transforms["tag_002"]
    scale = data.transforms["tag_001"][0]
    old_difference = _sample_columns()["sp"] - _sample_columns()["pv"]
    new_difference = data.columns["tag_002"] - data.columns["tag_001"]
    assert np.allclose(new_difference, scale * old_difference)


def test_keep_values_columns_keep_their_values() -> None:
    """A kept column is renamed only: transform (1, 0), so values are bit-identical."""
    columns = _sample_columns() | {"mode": np.array([0.0, 1.0, 2.0] * 66 + [0.0, 1.0])}
    t_s = _sample_time()

    data = anonymise(t_s, columns, keep_values=["mode"], seed=3)

    assert data.transforms["tag_003"] == (1.0, 0.0)
    assert np.array_equal(data.columns["tag_003"], columns["mode"])


def test_every_scale_lies_in_the_configured_range() -> None:
    """Log-uniform in [0.5, 2.0]: always positive, so a trend never flips sign."""
    data = anonymise(_sample_time(), _sample_columns(), seed=4)

    for scale, _ in data.transforms.values():
        assert SCALE_LOG_MIN <= scale <= SCALE_LOG_MAX


def test_nan_stays_nan_at_the_same_positions() -> None:
    """Affine arithmetic leaves gaps where they are, so cleaning logic still applies."""
    columns = _sample_columns()
    columns["pv"] = columns["pv"].copy()
    columns["pv"][5] = np.nan
    columns["pv"][100] = np.nan

    data = anonymise(_sample_time(), columns, seed=5)

    assert np.isnan(data.columns["tag_001"][5])
    assert np.isnan(data.columns["tag_001"][100])
    assert not np.isnan(data.columns["tag_001"][6])


def test_time_is_shifted_by_a_whole_number_of_seconds() -> None:
    """Sample spacing is untouched; only the absolute clock moves, by whole seconds."""
    t_s = _sample_time()

    data = anonymise(t_s, _sample_columns(), seed=6)

    assert data.time_shift_s == int(data.time_shift_s)
    assert np.allclose(np.diff(data.t_s), np.diff(t_s))


def test_the_same_seed_reproduces_the_same_export() -> None:
    """Reproducibility lets the customer invert a re-run export with the same recipe."""
    t_s = _sample_time()
    columns = _sample_columns()

    first = anonymise(t_s, columns, seed=7)
    second = anonymise(t_s, columns, seed=7)

    assert first.time_shift_s == second.time_shift_s
    assert first.transforms == second.transforms
    assert np.array_equal(first.columns["tag_001"], second.columns["tag_001"])


def test_a_different_seed_gives_a_different_export() -> None:
    """Two seeds must not collide on the same shift and transform."""
    t_s = _sample_time()
    columns = _sample_columns()

    first = anonymise(t_s, columns, seed=8)
    second = anonymise(t_s, columns, seed=9)

    assert first.transforms != second.transforms


def test_inputs_are_not_mutated() -> None:
    """The caller keeps its own arrays and mapping: anonymise only reads them."""
    t_s = _sample_time()
    columns = _sample_columns()
    original_time = t_s.copy()
    original_pv = columns["pv"].copy()

    anonymise(t_s, columns, seed=10)

    assert np.array_equal(t_s, original_time)
    assert np.array_equal(columns["pv"], original_pv)


def test_invert_values_recovers_the_original_column() -> None:
    """old = (new - offset) / scale, the exact inverse of the applied affine map."""
    columns = _sample_columns()

    data = anonymise(_sample_time(), columns, seed=11)
    recovered = invert_values(data, "tag_001", data.columns["tag_001"])

    assert np.allclose(recovered, columns["pv"])


def test_a_linked_tag_that_is_not_a_column_raises() -> None:
    """A typo in a group must fail loudly, not silently skip the grouping."""
    with pytest.raises(ValueError, match="is not a column"):
        anonymise(_sample_time(), _sample_columns(), linked_groups=[["pv", "typo"]], seed=12)


def test_a_tag_in_two_groups_raises() -> None:
    """Two transforms for one tag are ambiguous, so the request is rejected."""
    with pytest.raises(ValueError, match="appears in two linked groups"):
        anonymise(
            _sample_time(),
            _sample_columns(),
            linked_groups=[["pv", "sp"], ["sp"]],
            seed=13,
        )


def test_a_column_of_the_wrong_length_raises() -> None:
    """Every column must have one sample per time stamp, or the alignment is broken."""
    columns = _sample_columns() | {"short": np.zeros(5)}

    with pytest.raises(ValueError, match="time has"):
        anonymise(_sample_time(), columns, seed=14)


def test_a_constant_column_gets_a_finite_offset() -> None:
    """A zero standard deviation would give offset 0; the fallback keeps the scale real."""
    columns = _sample_columns() | {"constant": np.full(SAMPLE_COUNT, 42.0)}

    data = anonymise(_sample_time(), columns, seed=15)

    scale, offset = data.transforms["tag_003"]
    assert np.isfinite(offset)
    assert offset != 0.0
    assert SCALE_LOG_MIN <= scale <= SCALE_LOG_MAX


def test_an_unknown_tag_passed_to_invert_values_raises() -> None:
    """Inverting a tag that was never anonymised must name the tags that exist."""
    data: AnonymisedData = anonymise(_sample_time(), _sample_columns(), seed=16)

    with pytest.raises(ValueError, match="unknown tag"):
        invert_values(data, "tag_999", np.zeros(SAMPLE_COUNT))


def test_a_group_with_a_zero_std_first_column_still_shares_a_transform() -> None:
    """The group transform is drawn from its first member, constant or not."""
    columns = {
        "constant": np.full(SAMPLE_COUNT, 3.0),
        "pv": np.sin(_sample_time() / 50.0),
    }

    data = anonymise(_sample_time(), columns, linked_groups=[["constant", "pv"]], seed=17)

    assert data.transforms["tag_001"] == data.transforms["tag_002"]
    assert np.isfinite(data.transforms["tag_001"][1])
    assert OFFSET_FALLBACK > 0.0
