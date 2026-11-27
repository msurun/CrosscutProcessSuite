"""Check chronological validation folds and purging in original row units.

Forward validation must never train on or after its prediction block.
"""

import numpy as np
import pytest
from crosscut_softsensor.pls import PlsModelError, cv_split, select_components


@pytest.mark.parametrize("fold_number", [0, 1, 2, 3])
def test_forward_fold_uses_only_rows_before_the_gap(fold_number: int) -> None:
    indices = np.arange(0, 200, 2)
    training, validation = cv_split(indices, 4, 7, forward_only=True)[fold_number]
    assert indices[training[-1]] < indices[validation[0]] - 7
    assert np.array_equal(validation, np.arange(validation[0], validation[-1] + 1))


def test_forward_blocks_score_each_row_after_warmup_once() -> None:
    splits = cv_split(np.arange(100), 4, 3, forward_only=True)
    scored = np.concatenate([validation for _, validation in splits])
    assert np.array_equal(scored, np.arange(20, 100))


@pytest.mark.parametrize("indices", [np.array([0, 2, 1]), np.array([0, 0, 2]),
                                     np.array([-1, 0, 1]), np.arange(10, dtype=float)])
def test_invalid_original_indices_are_refused(indices: np.ndarray) -> None:
    with pytest.raises(PlsModelError, match="indices"):
        cv_split(indices, 2, 0)


@pytest.mark.parametrize("gap", [-1, 0.5])
def test_invalid_gap_is_refused(gap: int) -> None:
    with pytest.raises(PlsModelError, match="gap"):
        cv_split(np.arange(30), 2, gap)


@pytest.mark.parametrize("blocks", [0, 1, 31, 2.5])
def test_invalid_block_count_is_refused(blocks: int) -> None:
    with pytest.raises(PlsModelError, match="block"):
        cv_split(np.arange(30), blocks, 0)


def test_forward_gap_with_too_little_history_is_refused() -> None:
    with pytest.raises(PlsModelError, match="too few training"):
        cv_split(np.arange(30), 4, 10, forward_only=True)


def test_component_selection_does_not_count_unscored_warmup() -> None:
    errors = np.array([[np.nan, np.nan], [4.0, 1.0], [4.0, 1.0]])
    scores, chosen = select_components(errors)
    assert scores == [2.0, 1.0]
    assert chosen == 2


def test_component_selection_requires_scored_rows() -> None:
    with pytest.raises(PlsModelError, match="scored"):
        select_components(np.full((3, 2), np.nan))
