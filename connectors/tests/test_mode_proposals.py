"""Tests of the operating-mode and equipment-group proposals on synthetic history (#145).

The history is three stop / start-up ramp / run cycles of a mill: speed is bimodal, the feed
has an upper band while running, and the pump tags switch together.
"""

import numpy as np
import pytest
from crosscut_connectors.mode_proposals import (
    propose_equipment,
    propose_from_history,
    propose_modes,
    split_threshold,
)

DT = 10.0
CYCLE = [("stop", 300), ("ramp", 20), ("run", 480)]


def _cycles() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Time axis, mill speed (rpm) and a running flag for three cycles."""
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
    """Mill speed, a feed with an upper band, a pump pair that switches together, a stray tag."""
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


def test_bimodal_tag_is_split_inside_the_gap(history) -> None:
    """The threshold lies between the stopped and running clusters with high separation."""
    split = split_threshold(history[1]["ML1_SPEED"])
    assert split is not None
    assert split.gap[0] < split.threshold < split.gap[1]
    assert split.separation > 0.9


def test_unimodal_tag_has_no_split() -> None:
    """Gaussian noise is not two clusters."""
    assert split_threshold(np.random.default_rng(1).normal(0, 1, 2000)) is None


def test_modes_found_with_evidence(history) -> None:
    """Stopped, start-up, normal and high-throughput conditions come with share and windows."""
    t_s, values = history
    found = {m["id"]: m for m in propose_modes("ML1", ["ML1_SPEED", "ML1_FEED_FLOW"], t_s, values)}
    assert set(found) == {"ML1_stopped", "ML1_startup", "ML1_normal", "ML1_high_throughput"}
    stopped = found["ML1_stopped"]
    assert stopped["entry"]["condition"]["clauses"][0]["op"] == "<="
    assert 0.3 < stopped["evidence"]["share"] < 0.4
    assert stopped["evidence"]["events"] == 3 and len(stopped["evidence"]["windows"]) == 3
    assert stopped["confidence"] == "high"
    assert found["ML1_startup"]["evidence"]["events"] == 3
    high = found["ML1_high_throughput"]
    assert high["entry"]["condition"]["clauses"][1]["tag"] == "ML1_FEED_FLOW"
    assert 0.0 < high["evidence"]["share"] < 0.15


def test_start_up_window_covers_the_ramp(history) -> None:
    """The first start-up window lies on the first ramp (samples 300-319, i.e. 3000-3190 s)."""
    t_s, values = history
    modes = propose_modes("ML1", ["ML1_SPEED"], t_s, values)
    start, end = next(m for m in modes if m["id"] == "ML1_startup")["evidence"]["windows"][0]
    assert 3000 <= start < end <= 3200


def test_constant_tag_gives_no_modes() -> None:
    """A tag that never changes proposes nothing."""
    t_s = np.arange(500.0)
    assert propose_modes("X", ["X_SPEED"], t_s, {"X_SPEED": np.full(500, 50.0)}) == []


def test_co_switching_tags_form_equipment(history) -> None:
    """The pump pair is proposed as equipment; the uncorrelated ambient tag is left out."""
    groups = {g["id"]: g for g in propose_equipment(history[1], set(), set())}
    assert groups["PMP7"]["entry"]["tags"] == ["PMP7_CURR", "PMP7_RUN"]
    assert groups["PMP7"]["evidence"]["kind"] == "co_switching"
    assert groups["PMP7"]["confidence"] == "high"
    assert "PMP7_AMB" not in groups["PMP7"]["entry"]["tags"]


def test_attached_or_existing_equipment_is_not_proposed(history) -> None:
    """Tags already on equipment and ids already in use are skipped."""
    values = {k: v for k, v in history[1].items() if k.startswith("PMP7")}
    assert propose_equipment(values, {"PMP7_RUN"}, set()) == []
    assert all(g["id"] != "PMP7" for g in propose_equipment(values, set(), {"PMP7"}))


def test_site_proposals_cover_existing_and_new_equipment(history) -> None:
    """Leaf equipment gets modes; a proposed group's modes are flagged scope_new."""
    t_s, values = history
    site = {
        "equipment": [
            {"id": "site", "level": "site"},
            {"id": "ML1", "level": "equipment", "parent": "site", "tags": ["ML1_SPEED"]},
        ],
        "modes": [{"id": "ML1_stopped"}],
    }
    result = propose_from_history(t_s, values, site)
    ids = {m["id"]: m for m in result["modes"]}
    assert "ML1_stopped" not in ids and "ML1_startup" in ids
    assert not ids["ML1_startup"].get("scope_new")
    assert ids["PMP7_stopped"]["scope_new"] is True
    assert "PMP7" in {g["id"] for g in result["equipment"]}
