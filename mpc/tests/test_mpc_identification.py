"""Identify the Wood-Berry matrix from simulated one-at-a-time step tests and test the artifact.

The published coefficients come from the sim package, so the truth is not copied here.
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from crosscut_mpc import (
    Dataset,
    IdentificationRejected,
    IdentModelIntegrityError,
    PairSpec,
    identify_mimo,
    load_ident_model,
    save_ident_model,
)
from crosscut_sim.core import MAN, Scenario
from crosscut_sim.plants.wood_berry import (
    BOT,
    BOT_MODE,
    DEAD_TIME_MATRIX_MIN,
    DISTURBANCE_DEAD_TIMES_MIN,
    DISTURBANCE_GAINS,
    DISTURBANCE_TIME_CONSTANTS_MIN,
    FEED,
    GAIN_MATRIX,
    NOMINAL,
    REFLUX,
    STEAM,
    TIME_CONSTANT_MATRIX_MIN,
    TOP,
    TOP_MODE,
    WoodBerryPlant,
)

DT_S = 60.0  # one sample per minute
BLOCK = 300  # samples per block: a step up, then back, each settling (5 tau + delay)
STEP = {"reflux": 0.1, "steam": 0.1, "feed": 0.1}  # step sizes in lb/min
INPUTS = ("reflux", "steam", "feed")
TAGS = {"reflux": REFLUX, "steam": STEAM, "feed": FEED}


def run_step_tests(skip: tuple[str, ...] = ()) -> Dataset:
    """Pulse reflux, steam and feed rate in turn (one block each) on the manual plant."""
    plant = WoodBerryPlant()
    plant.reset(0, Scenario(dt_s=DT_S, measurement_noise=0.0))
    plant.write(TOP_MODE, MAN)
    plant.write(BOT_MODE, MAN)
    levels = {name: NOMINAL[name if name != "feed" else "feed_rate"] for name in INPUTS}
    u = {name: [] for name in INPUTS}
    y = {"top_comp": [], "bottom_comp": []}
    for name in INPUTS:
        for k in range(BLOCK):
            if name not in skip and k in (5, BLOCK // 2):
                levels[name] += STEP[name] if k == 5 else -STEP[name]  # up, then back
            plant.write(TAGS[name], levels[name])
            plant.step()
            for tag in INPUTS:
                u[tag].append(plant.read(TAGS[tag])[0])
            y["top_comp"].append(plant.read(TOP)[0])
            y["bottom_comp"].append(plant.read(BOT)[0])
    n = 3 * BLOCK
    return Dataset(
        np.arange(n) * DT_S,
        {k: np.array(v) for k, v in u.items()},
        {k: np.array(v) for k, v in y.items()},
    )


def all_pairs() -> list[PairSpec]:
    """Each input is identified on its own block."""
    return [
        PairSpec(name, cv, i * BLOCK, (i + 1) * BLOCK)
        for i, name in enumerate(INPUTS)
        for cv in ("top_comp", "bottom_comp")
    ]


def truth() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Published (CV, input) matrices with the feed column appended, times in seconds."""
    gains = np.column_stack((GAIN_MATRIX, DISTURBANCE_GAINS))
    taus = np.column_stack((TIME_CONSTANT_MATRIX_MIN, DISTURBANCE_TIME_CONSTANTS_MIN)) * 60.0
    delays = np.column_stack((DEAD_TIME_MATRIX_MIN, DISTURBANCE_DEAD_TIMES_MIN)) * 60.0
    return gains, taus, delays


@pytest.fixture(scope="module")
def identified():
    """Identify once for the module: the plant run is the slow part."""
    return identify_mimo(run_step_tests(), all_pairs(), max_delay_s=15 * 60.0)


def test_identified_matrix_matches_wood_berry(identified):
    gains, taus, delays = truth()
    assert identified.accepted
    np.testing.assert_allclose(identified.gains, gains, rtol=0.08)
    np.testing.assert_allclose(identified.time_constants_s, taus, rtol=0.2)
    np.testing.assert_allclose(identified.dead_times_s, delays, atol=2 * DT_S)


def test_identified_model_feeds_the_mpc_model(identified):
    model = identified.to_mpc_model()
    assert model.gains.shape == (2, 3)


def test_pair_without_excitation_fails_the_gate():
    result = identify_mimo(run_step_tests(skip=("steam",)), all_pairs(), max_delay_s=15 * 60.0)
    assert not result.accepted
    assert not result.quality[0][1].passed and not result.quality[1][1].passed
    assert result.quality[0][0].passed
    with pytest.raises(IdentificationRejected, match="steam->top_comp"):
        result.to_mpc_model()


def test_pairs_must_cover_the_matrix():
    with pytest.raises(ValueError, match="every"):
        identify_mimo(run_step_tests(), all_pairs()[:-1], max_delay_s=15 * 60.0)


def test_artifact_round_trip(identified, tmp_path):
    digest = save_ident_model(tmp_path / "m", identified, created_utc="2026-01-01T00:00:00Z")
    loaded = load_ident_model(tmp_path / "m", expected_sha256=digest)
    np.testing.assert_array_equal(loaded.gains, identified.gains)
    np.testing.assert_array_equal(loaded.time_constants_s, identified.time_constants_s)
    np.testing.assert_array_equal(loaded.dead_times_s, identified.dead_times_s)
    assert loaded.input_names == identified.input_names
    assert loaded.windows == identified.windows
    assert loaded.quality == identified.quality
    assert loaded.accepted


def test_tampered_payload_is_refused(identified, tmp_path):
    save_ident_model(tmp_path / "m", identified)
    payload = tmp_path / "m" / "model.json"
    doc = json.loads(payload.read_text(encoding="utf-8"))
    doc["gains"][0][0] = 99.0
    payload.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(IdentModelIntegrityError):
        load_ident_model(tmp_path / "m")


def test_wrong_catalogue_hash_is_refused(identified, tmp_path):
    save_ident_model(tmp_path / "m", identified)
    with pytest.raises(IdentModelIntegrityError, match="catalogue"):
        load_ident_model(tmp_path / "m", expected_sha256="0" * 64)


def test_identification_and_artifact_are_deterministic(identified, tmp_path):
    again = identify_mimo(run_step_tests(), all_pairs(), max_delay_s=15 * 60.0)
    first = save_ident_model(tmp_path / "a", identified, created_utc="2026-01-01T00:00:00Z")
    second = save_ident_model(tmp_path / "b", again, created_utc="2026-01-01T00:00:00Z")
    assert first == second
    assert (tmp_path / "a" / "manifest.json").read_bytes() == (
        tmp_path / "b" / "manifest.json").read_bytes()
    shutil.rmtree(Path(tmp_path))
