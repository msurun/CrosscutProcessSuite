"""Backup mode: the virtual sensor substitutes an invalid measurement, with hysteresis.

Per row the measured value is checked (flag tag, bad quality = no good sample, range, frozen).
A state machine runs causally: an invalid row switches to ``backup`` at once; the measurement
returns only after it was valid for ``return_hold_s`` without a break, so a value flickering
around a limit cannot chatter between the two sources. Every switch is logged as
{t_s, from, to, reason}. Output quality code: 0 measured, 1 substituted, 2 unavailable
(measurement invalid and no model value either).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from crosscut_softsensor.config import BackupConfig

MEASURED, BACKUP = "measured", "backup"
GOOD, SUBSTITUTED, UNAVAILABLE = 0, 1, 2
RETURNED = "measurement_valid"


@dataclass(frozen=True, eq=False)
class BackupResult:
    """Output series with substitution flag and quality code, the invalid reasons and the log."""

    output: np.ndarray
    substituted: np.ndarray
    quality: np.ndarray
    reason: list[str]
    switches: list[dict[str, object]]


def invalid_reasons(
    measured: np.ndarray, flag: np.ndarray | None, t_s: np.ndarray, cfg: BackupConfig
) -> list[str]:
    """Reason per row why the measurement is invalid ("" = valid); flag, quality, range, frozen."""
    frozen = _frozen(measured, t_s, cfg.frozen_s)
    out = []
    for i, value in enumerate(measured):
        if flag is not None and np.isfinite(flag[i]) and flag[i] != 0:
            out.append("analyser_flag")
        elif not np.isfinite(value):
            out.append("bad_quality")
        elif value < cfg.range_lo or value > cfg.range_hi:
            out.append("out_of_range")
        else:
            out.append("frozen" if frozen[i] else "")
    return out


def _frozen(values: np.ndarray, t_s: np.ndarray, frozen_s: float) -> np.ndarray:
    """True where the value has been exactly unchanged for at least ``frozen_s`` seconds."""
    out = np.zeros(len(values), dtype=bool)
    start = 0
    for i in range(len(values)):
        if i == 0 or not np.isfinite(values[i]) or values[i] != values[i - 1]:
            start = i
        out[i] = bool(np.isfinite(values[i])) and t_s[i] - t_s[start] >= frozen_s
    return out


def run_backup(
    t_s: np.ndarray,
    measured: np.ndarray,
    flag: np.ndarray | None,
    virtual: np.ndarray,
    cfg: BackupConfig,
) -> BackupResult:
    """Choose per row between the measurement and the virtual value and log every switch."""
    reasons = invalid_reasons(measured, flag, t_s, cfg)
    states, switches = _state_machine(t_s, reasons, cfg.return_hold_s)
    use_backup = np.array([s == BACKUP for s in states], dtype=bool)
    output = np.where(use_backup, virtual, measured)
    quality = np.where(~use_backup, GOOD, np.where(np.isfinite(virtual), SUBSTITUTED, UNAVAILABLE))
    return BackupResult(output, use_backup, quality.astype(int), reasons, switches)


def _state_machine(
    t_s: np.ndarray, reasons: list[str], hold_s: float
) -> tuple[list[str], list[dict[str, object]]]:
    """Causal two-state machine: invalid row -> backup, ``hold_s`` of validity -> measured."""
    state, valid_since = MEASURED, None
    states, switches = [], []
    for t, reason in zip(t_s, reasons, strict=True):
        previous = state
        state, valid_since, why = _step(state, valid_since, float(t), reason, hold_s)
        if state != previous:
            switches.append({"t_s": float(t), "from": previous, "to": state, "reason": why})
        states.append(state)
    return states, switches


def _step(
    state: str, valid_since: float | None, t: float, reason: str, hold_s: float
) -> tuple[str, float | None, str]:
    """One row of the state machine: (new state, start of the current valid run, switch reason)."""
    if reason:
        return BACKUP, None, reason
    since = t if valid_since is None else valid_since
    if state == BACKUP and t - since >= hold_s:
        return MEASURED, since, RETURNED
    return state, since, ""


def backup_columns(
    columns: Mapping[str, np.ndarray], cfg: BackupConfig
) -> tuple[np.ndarray, np.ndarray | None]:
    """The measured column and the optional flag column from the binned columns."""
    flag = None if cfg.flag_tag is None else np.asarray(columns[cfg.flag_tag], dtype=float)
    return np.asarray(columns[cfg.measured_tag], dtype=float), flag
