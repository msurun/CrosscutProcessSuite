"""Catalogue of the 20 simulated loops of the blind-review pack (author's injected truth).

Each ``LoopSpec`` holds process dynamics, controller tuning, the injected fault and the
author's expected best next action. Gains are engineering units per % of valve opening
(for integrating loops: engineering units per second per %). The loop order is shuffled with
a fixed seed so that the sheet order does not reveal the cause.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KindInfo:
    """Tag prefix, unit, engineering range and operating point of one loop kind."""

    prefix: str
    unit: str
    eng_min: float
    eng_max: float
    pv0: float


KINDS = {
    "flow": KindInfo("FIC", "m3/h", 0.0, 200.0, 120.0),
    "temperature": KindInfo("TIC", "degC", 0.0, 150.0, 85.0),
    "level": KindInfo("LIC", "%", 0.0, 100.0, 50.0),
    "pressure": KindInfo("PIC", "bar", 0.0, 10.0, 5.0),
}


@dataclass(frozen=True)
class LoopSpec:
    """Everything needed to simulate one loop and to describe its injected truth."""

    kind: str
    cause: str
    category: str
    action: str
    author_rank: int
    gain: float
    tau_s: float
    delay_s: float
    kc: float
    ti_s: float
    noise: float
    ou_sigma: float = 1.0  # load disturbance in % of valve opening
    ou_tau_s: float = 1200.0
    ou_mean: float = 0.0
    deadband: float = 0.0
    jump: float = 0.0
    period_s: float = 0.0
    period_amp: float = 0.0
    period_phase: float = 0.0
    load_steps: tuple[tuple[float, float], ...] = ()  # (hour, % of opening)
    sp_steps: tuple[tuple[float, float], ...] = ()  # (hour, engineering units)
    auto_fraction: float = 1.0
    frozen: tuple[float, float] | None = None
    quant: float = 0.0
    extras: dict[str, float] = field(default_factory=dict)

    @property
    def integrating(self) -> bool:
        """True for a level loop (the process integrates the valve flow)."""
        return self.kind == "level"


def _healthy() -> list[LoopSpec]:
    """Five healthy loops with different dynamics."""
    act = "None: loop is healthy, leave it alone (lowest priority)."
    base = {"cause": "healthy", "category": "none", "action": act}
    return [
        LoopSpec(
            "flow",
            **base,
            author_rank=14,
            gain=2.0,
            tau_s=30,
            delay_s=10,
            kc=0.3,
            ti_s=35,
            noise=0.5,
            sp_steps=((3.0, 10.0),),
        ),
        LoopSpec(
            "temperature",
            **base,
            author_rank=15,
            gain=0.6,
            tau_s=240,
            delay_s=40,
            kc=1.0,
            ti_s=240,
            noise=0.15,
            ou_sigma=1.5,
            ou_tau_s=1800,
        ),
        LoopSpec(
            "level",
            **base,
            author_rank=16,
            gain=0.0005,
            tau_s=15,
            delay_s=10,
            kc=6.0,
            ti_s=1200,
            noise=0.15,
            ou_sigma=1.5,
        ),
        LoopSpec(
            "pressure",
            **base,
            author_rank=17,
            gain=0.05,
            tau_s=90,
            delay_s=20,
            kc=8.0,
            ti_s=100,
            noise=0.01,
            sp_steps=((2.5, 0.2),),
        ),
        LoopSpec(
            "flow",
            **base,
            author_rank=20,
            gain=1.5,
            tau_s=60,
            delay_s=20,
            kc=0.4,
            ti_s=70,
            noise=0.4,
        ),
    ]


def _stiction() -> list[LoopSpec]:
    """Three PI loops with a sticking valve, different deadbands."""
    act = "Check the control valve for stiction (positioner, packing); plan valve maintenance."
    base = {"cause": "valve stiction", "category": "valve/stiction", "action": act}
    return [
        LoopSpec(
            "flow",
            **base,
            author_rank=6,
            gain=2.0,
            tau_s=30,
            delay_s=10,
            kc=0.5,
            ti_s=15,
            noise=0.5,
            ou_sigma=0.2,
            deadband=2.0,
            jump=0.6,
        ),
        LoopSpec(
            "flow",
            **base,
            author_rank=5,
            gain=1.5,
            tau_s=60,
            delay_s=20,
            kc=0.7,
            ti_s=30,
            noise=0.4,
            ou_sigma=0.2,
            deadband=3.5,
            jump=1.0,
        ),
        LoopSpec(
            "pressure",
            **base,
            author_rank=7,
            gain=0.05,
            tau_s=90,
            delay_s=20,
            kc=12.0,
            ti_s=25,
            noise=0.01,
            ou_sigma=0.2,
            deadband=6.0,
            jump=2.0,
        ),
    ]


def _external() -> list[LoopSpec]:
    """Two loops driven by the same 22 min periodic disturbance (not their own fault)."""
    act = (
        "Find the common source of the 22 min cycle (upstream unit or cycling loop); "
        "do not retune these loops."
    )
    base = {
        "cause": "shared periodic external disturbance (1320 s)",
        "category": "external disturbance",
        "action": act,
        "period_s": 1320.0,
    }
    return [
        LoopSpec(
            "temperature",
            **base,
            author_rank=8,
            gain=0.6,
            tau_s=240,
            delay_s=40,
            kc=1.0,
            ti_s=240,
            noise=0.15,
            period_amp=6.0,
        ),
        LoopSpec(
            "pressure",
            **base,
            author_rank=9,
            gain=0.05,
            tau_s=90,
            delay_s=20,
            kc=8.0,
            ti_s=100,
            noise=0.01,
            period_amp=3.0,
            period_phase=0.4,
        ),
    ]


def _tuning() -> list[LoopSpec]:
    """Two aggressive and two sluggish loops."""
    aggr = {
        "cause": "tuning too aggressive",
        "category": "tuning aggressive",
        "action": "Retune: reduce controller gain and/or lengthen integral time.",
    }
    slow = {
        "cause": "tuning sluggish (gain 0.2x)",
        "category": "tuning sluggish",
        "action": "Retune: raise controller gain / shorten integral time.",
    }
    return [
        LoopSpec(
            "temperature",
            **aggr,
            author_rank=3,
            gain=0.6,
            tau_s=200,
            delay_s=50,
            kc=9.0,
            ti_s=200,
            noise=0.15,
        ),
        LoopSpec(
            "flow",
            **aggr,
            author_rank=4,
            gain=2.0,
            tau_s=40,
            delay_s=20,
            kc=1.12,
            ti_s=40,
            noise=0.5,
        ),
        LoopSpec(
            "temperature",
            **slow,
            author_rank=12,
            gain=0.6,
            tau_s=240,
            delay_s=40,
            kc=0.2,
            ti_s=240,
            noise=0.15,
            ou_sigma=1.5,
            ou_tau_s=1800,
            sp_steps=((3.0, 3.0),),
        ),
        LoopSpec(
            "level",
            **slow,
            author_rank=13,
            gain=0.0005,
            tau_s=15,
            delay_s=10,
            kc=1.2,
            ti_s=1200,
            noise=0.15,
            ou_sigma=1.5,
        ),
    ]


def _faults() -> list[LoopSpec]:
    """Saturation, manual mode, frozen PV, coarse output resolution."""
    return [
        LoopSpec(
            "flow",
            "output saturated at 100 %",
            "saturation",
            "Output sits at 100 %: check valve size, supply or SP reachability; not tuning.",
            1,
            2.0,
            30,
            10,
            0.3,
            35,
            0.5,
            ou_sigma=5.0,
            ou_mean=-56.0,
        ),
        LoopSpec(
            "temperature",
            "mostly in MANUAL",
            "manual",
            "Ask the operator why it is in manual; return to auto or fix what blocks it.",
            10,
            0.5,
            300,
            60,
            0.8,
            300,
            0.15,
            ou_sigma=2.5,
            ou_tau_s=3000,
            auto_fraction=0.14,
        ),
        LoopSpec(
            "pressure",
            "frozen PV for 30 % of the record",
            "measurement/instrument",
            "Check the pressure transmitter, wiring or comms: PV stuck for about 2 h.",
            2,
            0.05,
            90,
            20,
            8.0,
            100,
            0.01,
            frozen=(0.40, 0.70),
        ),
        LoopSpec(
            "temperature",
            "coarse output resolution (1 % steps)",
            "measurement/instrument",
            "Check output resolution of the AO card / positioner scaling (1 % steps).",
            11,
            0.04,
            200,
            30,
            15.0,
            200,
            0.10,
            ou_sigma=0.5,
            quant=1.0,
        ),
    ]


def _load_steps() -> list[LoopSpec]:
    """Two healthy loops hit by load steps at hours 2 and 4 (loop copes, no fault)."""
    act = "None: loop handles the load steps acceptably; no action, just watch."
    base = {
        "cause": "healthy, load steps at 2 h and 4 h",
        "category": "none",
        "action": act,
        "author_rank": 18,
    }
    return [
        LoopSpec(
            "temperature",
            **base,
            gain=0.8,
            tau_s=300,
            delay_s=50,
            kc=0.9,
            ti_s=300,
            noise=0.15,
            load_steps=((2.0, 8.0), (4.0, 8.0)),
        ),
        LoopSpec(
            "pressure",
            **{**base, "author_rank": 19},
            gain=0.05,
            tau_s=90,
            delay_s=20,
            kc=8.0,
            ti_s=100,
            noise=0.01,
            load_steps=((2.0, 10.0), (4.0, -10.0)),
        ),
    ]


def build_catalog(shuffle_seed: int = 2025) -> list[LoopSpec]:
    """All 20 loop specs in the (shuffled) sheet order; loop number = index + 1."""
    specs = _healthy() + _stiction() + _external() + _tuning() + _faults() + _load_steps()
    random.Random(shuffle_seed).shuffle(specs)
    return specs


def tag_name(number: int, spec: LoopSpec) -> str:
    """Neutral tag name such as ``FIC-103`` for loop ``number`` (1-based)."""
    return f"{KINDS[spec.kind].prefix}-{100 + number}"
