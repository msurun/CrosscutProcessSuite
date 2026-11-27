"""Edge cases for mode and equipment proposals: flat, short or gappy histories, and evidence checks.
Complements test_mode_proposals.py (#145).
"""

from typing import Any

import numpy as np
import pytest
from crosscut_connectors.mode_proposals import (
    Doc,
    propose_equipment,
    propose_from_history,
    propose_modes,
    split_threshold,
)

DT = 10.0  # seconds between consecutive samples
FLAT_SAMPLES = 2000  # >= MIN_SAMPLES (50) so the Otsu split is really attempted before failing
SHORT_SAMPLES = 40  # < MIN_SAMPLES (50), the smallest sample-count floor the module defines
EVIDENCE_FIELDS = ("kind", "share", "thresholds", "windows", "events", "detail")


def _cycles() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Time axis (s), mill speed (rpm) and a running flag for three stop/ramp/run cycles."""
    rng = np.random.default_rng(145)
    pieces, running = [], []
    for _ in range(3):
        pieces += [
            rng.normal(0.5, 0.3, 300),
            np.linspace(5, 70, 20),
            rng.normal(75, 1.0, 480),
        ]
        running += [np.zeros(300), np.ones(20), np.ones(480)]
    speed = np.concatenate(pieces)
    return np.arange(speed.size) * DT, speed, np.concatenate(running)


@pytest.fixture()
def history() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Mill speed, a feed with an upper band, a pump pair that switches together."""
    t_s, speed, running = _cycles()
    rng = np.random.default_rng(7)
    feed = running * rng.normal(100, 3, speed.size)
    feed[(speed > 70) & (np.arange(speed.size) % 5 == 0)] += 40
    return t_s, {
        "ML1_SPEED": speed,
        "ML1_FEED_FLOW": feed,
        "PMP7_RUN": running * 1.0,
        "PMP7_CURR": running * 20 + rng.normal(0, 0.5, speed.size),
        "PMP7_AMB": rng.normal(20, 1, speed.size),
    }


def _square_wave(shift: int, period: int = 300, size: int = 2100,
                 level: float = 100.0) -> np.ndarray:
    """A 0/level square wave, one low and one high half per period, shifted by ``shift`` samples."""
    phase = (np.arange(size) + shift) % period
    return np.where(phase >= period // 2, level, 0.0)


def _site() -> Doc:
    """A minimal site document: mill ML1 as existing equipment, no known modes yet."""
    return {
        "equipment": [
            {"id": "site", "level": "site"},
            {
                "id": "ML1",
                "level": "equipment",
                "parent": "site",
                "tags": ["ML1_SPEED", "ML1_FEED_FLOW"],
            },
        ],
        "modes": [],
    }


def _numbers(value: Any, path: str = "evidence") -> list[tuple[str, float]]:
    """Every number nested inside ``value`` as (dotted path, value); text leaves are skipped."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [(path, float(value))]
    if isinstance(value, dict):
        return [(p, n) for key, item in value.items() for p, n in _numbers(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [(p, n) for i, item in enumerate(value) for p, n in _numbers(item, f"{path}[{i}]")]
    return []


def _assert_evidence_finite(proposal: Doc) -> None:
    """Raise AssertionError naming the path when evidence is incomplete or not finite."""
    evidence = proposal["evidence"]
    for field in EVIDENCE_FIELDS:
        assert field in evidence, f"proposal {proposal['id']} lacks evidence field {field!r}"
    for path, number in _numbers(evidence):
        message = f"proposal {proposal['id']} evidence at {path} is {number!r}, not finite"
        assert np.isfinite(number), message


def test_flat_activity_tag_proposes_no_stopped_mode() -> None:
    """A long unimodal speed tag (no stopped cluster) yields no proposals at all."""
    t_s = np.arange(FLAT_SAMPLES) * DT
    flat = np.random.default_rng(3).normal(50.0, 2.0, FLAT_SAMPLES)
    assert propose_modes("AG1", ["AG1_SPEED"], t_s, {"AG1_SPEED": flat}) == []


def test_nan_gaps_still_give_a_stopped_proposal() -> None:
    """NaN gaps inside a bimodal tag are ignored by the split and kept out of the evidence."""
    t_s, speed, _ = _cycles()
    gappy = np.array(speed, dtype=float)
    gappy[[100, 101, 1000, 420, 421]] = np.nan  # three gaps in stopped parts, two in running parts
    found = {m["id"]: m for m in propose_modes("ML1", ["ML1_SPEED"], t_s, {"ML1_SPEED": gappy})}
    stopped = found["ML1_stopped"]
    assert 0.3 < stopped["evidence"]["share"] < 0.4
    _assert_evidence_finite(stopped)


def test_history_shorter_than_min_samples_proposes_nothing() -> None:
    """Fewer than 50 samples give no stable histogram, so even a bimodal tag yields no modes."""
    t_s = np.arange(SHORT_SAMPLES) * DT
    half = SHORT_SAMPLES // 2
    short = np.concatenate([np.full(half, 0.0), np.full(half, 100.0)])
    assert propose_modes("ML9", ["ML9_SPEED"], t_s, {"ML9_SPEED": short}) == []


def test_prefix_candidates_without_co_switching_are_not_grouped() -> None:
    """Two bimodal tags sharing a prefix but uncorrelated and out of phase stay ungrouped."""
    speed = _square_wave(0)
    curr = _square_wave(75)  # switch times 75 samples apart; |corr| = 0 over the 7 full periods
    values = {"PMP9_SPEED": speed, "PMP9_CURR": curr}
    assert split_threshold(speed) is not None  # guard: both are clean bimodal candidates
    assert split_threshold(curr) is not None
    assert propose_equipment(values, set(), set()) == []


def test_every_proposal_carries_finite_evidence(history) -> None:
    """Every mode and equipment-group proposal carries complete evidence with finite numbers."""
    t_s, values = history
    result = propose_from_history(t_s, values, _site())
    proposals = [*result["modes"], *result["equipment"]]
    assert proposals, "expected at least one mode or equipment proposal"
    for proposal in proposals:
        _assert_evidence_finite(proposal)
