"""Generator G30: 21-day mill-circuit records with a hidden lab quality variable (exp30, README.md).

The harness author (not the soft sensor author) defines the hidden 'silica-like' quality here: a
fixed nonlinear function of the recorded tags (P80 included, it is never a module input) plus a
slow Ornstein-Uhlenbeck disturbance, sparse noisy lab samples, and the regime / drift scenarios.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
from crosscut_sim.plants.mill_circuit import HARD_MEAN, NOMINAL, MillCircuitPlant
from crosscut_sim.scenarios import build_scenario

SCENARIO = "observational"
TAG_NAMES = (
    "hpgr_press", "mill_feed", "cyc_water", "feed_moisture",
    "p80", "mill_power", "hpgr_power", "ore_hardness_est",
)
TAGS = tuple(f"sim.mc.{name}" for name in TAG_NAMES)  # recorded PV tags
P80_TAG = "sim.mc.p80"
INPUT_TAGS = tuple(t for t in TAGS if t != P80_TAG)  # module inputs: P80 withheld (protocol)
SCENARIOS = ("normal", "regime", "drift")  # cycled over the seeds (protocol)
RAW_PERIOD_S = 10.0  # raw sample period, s (plant dt = 1 s)
ROW_PERIOD_S = 60.0  # averaged row period, s (protocol: 60 s samples)
RAW_PER_ROW = int(ROW_PERIOD_S / RAW_PERIOD_S)
DAY_S = 86400.0
HOUR_S = 3600.0
LAB_PERIOD_S = 4 * HOUR_S  # one lab sample every 4 h
LAB_DELAY_S = 3600.0  # lab result available 1 h after the sample time
LAB_SD = 0.3  # lab noise, units of the hidden variable's standard deviation
OU_TAU_S = 2 * DAY_S  # unmodelled disturbance time constant (protocol: 2 days)
# Harness choice fixed before any seed ran: stationary sd of the OU part. The deterministic part
# is scaled to sd sqrt(1 - OU_SD**2) on the training period, so the noise-free variable has sd ~1.
OU_SD = 0.3
DRIFT_PER_DAY = 0.1  # protocol: 0.1 standard deviation per day
DRIFT_TAG = "sim.mc.mill_feed"  # harness choice: the tag whose dependence drifts
HARDNESS_OU_SD = 1.5  # simulator's stationary sd of the true hardness, kWh/t
REGIME_MARGIN = 2 * HARDNESS_OU_SD  # new hardness mean = training max + 2 sd (kWh/t)
STREAM = 30  # first word after the seed in the harness RNG seeds [seed, STREAM, k]


@dataclass(frozen=True)
class Durations:
    """Record timing in days (regime length in hours); defaults are the frozen protocol values."""

    total_d: float = 21.0
    cut_d: float = 14.0
    drift_start_d: float = 15.0
    regime_start_d: float = 16.0
    regime_h: float = 24.0


PROTOCOL = Durations()


@dataclass(frozen=True)
class Record:
    """One record: 60 s rows of the TAGS, the true hardness, the hidden truth and the lab.

    ``t_s`` stamps each row at its last raw sample (window start + 50 s). ``lab_t_s`` are lab
    sample times (exact row times), ``lab_values`` the noisy lab results; each is available at
    ``lab_t_s + LAB_DELAY_S``.
    """

    t_s: np.ndarray
    x: np.ndarray  # rows by TAGS, engineering units (60 s means of 10 s samples)
    hardness: np.ndarray  # true ore hardness per row (60 s mean), kWh/t; hidden from the module
    truth: np.ndarray  # hidden quality variable per row (noise-free, OU included)
    lab_t_s: np.ndarray
    lab_values: np.ndarray
    meta: dict

    def columns(self) -> dict[str, np.ndarray]:
        """Tag name -> 60 s series, as the module's feature builder takes them."""
        return {tag: self.x[:, j] for j, tag in enumerate(TAGS)}


def scenario_of(index: int) -> str:
    """Scenario of the seed at position ``index`` of its seed range (normal, regime, drift)."""
    return SCENARIOS[index % len(SCENARIOS)]


def _plant(seed: int, durations: Durations) -> MillCircuitPlant:
    """A reset mill-circuit plant in the observational scenario."""
    scenario = build_scenario("mill_circuit", SCENARIO, duration_s=durations.total_d * DAY_S)
    plant = MillCircuitPlant()
    plant.reset(seed, scenario)
    return plant


Action = Callable[[MillCircuitPlant, np.ndarray], None]


def _sample(plant: MillCircuitPlant, n_raw: int, actions: dict[int, Action]) -> tuple:
    """Tag values and true hardness every 10 s; ``actions[i]`` runs before raw sample i.

    An action gets the plant and the raw true-hardness samples recorded so far.
    """
    values, hard = np.empty((n_raw, len(TAGS))), np.empty(n_raw)
    for i in range(n_raw):
        if i in actions:
            actions[i](plant, hard[:i])
        values[i] = [plant.read(tag)[0] for tag in TAGS]
        hard[i] = plant.true_hardness
        for _ in range(int(RAW_PERIOD_S)):
            plant.step()
    return values, hard


def _rows(raw: np.ndarray) -> np.ndarray:
    """60 s block means of 10 s samples (leading axis)."""
    n = len(raw) // RAW_PER_ROW
    return raw[: n * RAW_PER_ROW].reshape((n, RAW_PER_ROW) + raw.shape[1:]).mean(axis=1)


def _regime_actions(durations: Durations, meta: dict) -> dict[int, Action]:
    """Hardness-mean writes: up at regime start (training max + margin), back after regime_h.

    The training range is that of the 60 s true-hardness rows before the cut; the new mean is
    written to the simulator's driver tag ``sim.mc.hardness_mean`` (the plant then moves every
    hardness-dependent tag, including the ore_hardness_est the module sees).
    """
    i_cut = int(durations.cut_d * DAY_S / RAW_PERIOD_S)
    i_on = int(durations.regime_start_d * DAY_S / RAW_PERIOD_S)
    i_off = i_on + int(durations.regime_h * HOUR_S / RAW_PERIOD_S)

    def shift(plant: MillCircuitPlant, hard: np.ndarray) -> None:
        level = float(_rows(hard[:i_cut]).max()) + REGIME_MARGIN
        meta["regime"] = {"start_s": i_on * RAW_PERIOD_S, "end_s": i_off * RAW_PERIOD_S,
                          "hardness_mean": level}
        plant.write(HARD_MEAN, level)

    def restore(plant: MillCircuitPlant, hard: np.ndarray) -> None:
        plant.write(HARD_MEAN, NOMINAL["ore_hardness"])

    return {i_on: shift, i_off: restore}


def hidden_part(x: np.ndarray, train: np.ndarray) -> np.ndarray:
    """Deterministic part of the hidden quality, sd sqrt(1 - OU_SD**2) on the training rows.

    z are the tags standardised by the training-row mean and sd. Model (fixed before any seed):
    g = 0.8 z_p80 + 0.25 z_p80^2 - 0.35 z_water + 0.3 z_feed z_moist
        + 0.25 z_press z_hard_est + 0.2 tanh(z_mill_power)
    then centred and scaled by g's own training mean and sd.
    """
    z = (x - x[train].mean(axis=0)) / x[train].std(axis=0, ddof=1)
    c = {name: z[:, j] for j, name in enumerate(TAG_NAMES)}
    g = (0.8 * c["p80"] + 0.25 * c["p80"] ** 2 - 0.35 * c["cyc_water"]
         + 0.3 * c["mill_feed"] * c["feed_moisture"]
         + 0.25 * c["hpgr_press"] * c["ore_hardness_est"] + 0.2 * np.tanh(c["mill_power"]))
    return (g - g[train].mean()) / g[train].std(ddof=1) * np.sqrt(1.0 - OU_SD**2)


def ou_path(n: int, rng: np.random.Generator) -> np.ndarray:
    """Exact AR(1) discretisation at 60 s of an OU process (sd OU_SD, tau OU_TAU_S), stationary."""
    a = np.exp(-ROW_PERIOD_S / OU_TAU_S)
    kicks = rng.normal(0.0, OU_SD * np.sqrt(1.0 - a * a), n)
    out = np.empty(n)
    out[0] = rng.normal(0.0, OU_SD)
    for i in range(1, n):
        out[i] = a * out[i - 1] + kicks[i]
    return out


def drift_term(t_s: np.ndarray, x: np.ndarray, train: np.ndarray, start_s: float) -> np.ndarray:
    """Drift of the dependence on DRIFT_TAG: 0.1 sd per day times the tag over its training mean.

    term = DRIFT_PER_DAY * days_since_onset * x_tag / mean_train(x_tag); zero before the onset.
    The ratio is ~1 (mill feed varies by a few %), so the hidden variable moves ~0.1 sd per day
    and the move follows the tag.
    """
    j = TAGS.index(DRIFT_TAG)
    days = np.clip((t_s - start_s) / DAY_S, 0.0, None)
    return DRIFT_PER_DAY * days * x[:, j] / x[train, j].mean()


def _labs(t_s: np.ndarray, truth: np.ndarray, rng: np.random.Generator) -> tuple:
    """Lab samples every 4 h at exact row times (first at 4 h), noise sd LAB_SD."""
    rows = np.arange(int(LAB_PERIOD_S / ROW_PERIOD_S), len(t_s), int(LAB_PERIOD_S / ROW_PERIOD_S))
    return t_s[rows], truth[rows] + rng.normal(0.0, LAB_SD, len(rows))


def record(seed: int, scenario: str, durations: Durations = PROTOCOL) -> Record:
    """The record of one seed: plant seed = seed; harness RNGs [seed, 30, 1] (OU), [.., 2] (lab)."""
    meta: dict = {"seed": seed, "scenario": scenario, "durations": asdict(durations)}
    actions = _regime_actions(durations, meta) if scenario == "regime" else {}
    n_raw = int(round(durations.total_d * DAY_S / RAW_PERIOD_S))
    values, hard = _sample(_plant(seed, durations), n_raw, actions)
    x, hardness = _rows(values), _rows(hard)
    t_s = np.arange(len(x)) * ROW_PERIOD_S + (RAW_PER_ROW - 1) * RAW_PERIOD_S
    train = t_s < durations.cut_d * DAY_S
    truth = hidden_part(x, train) + ou_path(len(x), np.random.default_rng([seed, STREAM, 1]))
    if scenario == "drift":
        meta["drift"] = {"start_s": durations.drift_start_d * DAY_S, "tag": DRIFT_TAG}
        truth = truth + drift_term(t_s, x, train, durations.drift_start_d * DAY_S)
    lab_t, lab_v = _labs(t_s, truth, np.random.default_rng([seed, STREAM, 2]))
    return Record(t_s, x, hardness, truth, lab_t, lab_v, meta)
