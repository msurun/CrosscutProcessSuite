"""Event detection on T2 and SPE: runs of limit exceedances become anomaly events.

The scan works on the sequence of valid rows only (no NaN, quality 0). Invalid rows are counted,
never imputed, and neither extend nor break a run. Advisory only: no plant writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from crosscut_anomaly.config import AnomalyConfig, AnomalyConfigError
from crosscut_anomaly.pca_model import PcaModel

TOP_TAGS = 3


@dataclass(frozen=True)
class AnomalyEvent:
    """One anomaly event; ``end_index`` is the last exceeding sample (inclusive)."""

    start_index: int
    end_index: int
    start_s: float
    end_s: float
    closed: bool
    peak_t2: float
    peak_spe: float
    peak_index: int
    top_spe_tags: tuple[str, ...]
    top_t2_tags: tuple[str, ...]
    exceeded: str
    n_samples: int


@dataclass(frozen=True)
class ScanResult:
    """Events of one scan plus the valid / skipped row counts."""

    events: tuple[AnomalyEvent, ...]
    n_valid: int
    n_skipped: int
    skipped_reasons: dict[str, int] = field(default_factory=dict)


class _Runs:
    """State machine over valid-sequence exceedance flags yielding (start, end, closed)."""

    def __init__(self, min_consecutive: int, close_after: int) -> None:
        self.min_consecutive = min_consecutive
        self.close_after = close_after
        self.run_start = 0
        self.run_len = 0
        self.open = False
        self.last_exc = 0
        self.quiet = 0

    def feed(self, pos: int, exceeds: bool) -> tuple[int, int, bool] | None:
        """Advance by one valid sample; return a finished event if one closed."""
        if not self.open:
            self._feed_idle(pos, exceeds)
            return None
        if exceeds:
            self.last_exc, self.quiet = pos, 0
            return None
        self.quiet += 1
        if self.quiet < self.close_after:
            return None
        return self._finish(True)

    def finish(self) -> tuple[int, int, bool] | None:
        """Return the still open event at the end of the data, if any."""
        return self._finish(False) if self.open else None

    def _feed_idle(self, pos: int, exceeds: bool) -> None:
        """Count a run of exceedances; open the event when it is long enough."""
        if not exceeds:
            self.run_len = 0
            return
        if self.run_len == 0:
            self.run_start = pos
        self.run_len += 1
        if self.run_len >= self.min_consecutive:
            self.open, self.last_exc, self.quiet = True, pos, 0

    def _finish(self, closed: bool) -> tuple[int, int, bool]:
        """Close the event and reset the run counter."""
        self.open, self.run_len = False, 0
        return self.run_start, self.last_exc, closed


def _validity(
    x: np.ndarray, quality: Sequence[float] | np.ndarray | None
) -> tuple[np.ndarray, int, int]:
    """Valid mask plus the number of rows skipped for NaN and for quality."""
    has_nan = np.isnan(x).any(axis=1)
    if quality is None:
        bad_q = np.zeros(len(x), dtype=bool)
    else:
        bad_q = np.asarray(quality, dtype=float) != 0
    return ~(has_nan | bad_q), int(has_nan.sum()), int((bad_q & ~has_nan).sum())


def _peak(ratio: np.ndarray, start: int, end: int) -> int:
    """Position of the largest limit ratio within the event."""
    return start + int(np.argmax(ratio[start : end + 1]))


def _top(shares: dict[str, float]) -> tuple[str, ...]:
    """The tags with the largest shares, largest first (ties keep tag order)."""
    ordered = sorted(shares, key=lambda tag: -shares[tag])
    return tuple(ordered[:TOP_TAGS])


def _exceeded(t2_flag: np.ndarray, spe_flag: np.ndarray) -> str:
    """Which statistic exceeded its limit within the event."""
    t2_hit, spe_hit = bool(t2_flag.any()), bool(spe_flag.any())
    return "both" if t2_hit and spe_hit else ("t2" if t2_hit else "spe")


def _event(
    model: PcaModel, span: tuple[int, int, bool], rows: np.ndarray,
    stats: tuple[np.ndarray, np.ndarray], orig: tuple[np.ndarray, np.ndarray],
) -> AnomalyEvent:
    """Build the event for valid positions ``span`` (start, end, closed)."""
    start, end, closed = span
    t2, spe = stats
    ratio = np.maximum(t2 / model.t2_limit, spe / model.spe_limit)
    peak = _peak(ratio, start, end)
    contrib = model.contributions(rows[peak])
    index, t_valid = orig
    return AnomalyEvent(
        start_index=int(index[start]), end_index=int(index[end]),
        start_s=float(t_valid[start]), end_s=float(t_valid[end]), closed=closed,
        peak_t2=float(t2[peak]), peak_spe=float(spe[peak]), peak_index=int(index[peak]),
        top_spe_tags=_top(contrib["spe"]), top_t2_tags=_top(contrib["t2"]),
        exceeded=_exceeded(t2[start : end + 1] > model.t2_limit,
                           spe[start : end + 1] > model.spe_limit),
        n_samples=end - start + 1,
    )


def _spans(exceed: np.ndarray, config: AnomalyConfig) -> list[tuple[int, int, bool]]:
    """Event spans (positions in the valid sequence) from exceedance flags."""
    runs = _Runs(config.min_consecutive, config.close_after)
    spans = [s for pos, flag in enumerate(exceed) if (s := runs.feed(pos, bool(flag)))]
    last = runs.finish()
    return spans + [last] if last else spans


def scan(
    model: PcaModel,
    t_s: Sequence[float] | np.ndarray,
    x: np.ndarray,
    quality: Sequence[float] | np.ndarray | None = None,
    config: AnomalyConfig | None = None,
) -> ScanResult:
    """Scan a record (samples by tags) and return its anomaly events.

    Raises:
        AnomalyConfigError: if ``config`` is missing.
    """
    if config is None:
        raise AnomalyConfigError("config: required")
    x = np.asarray(x, dtype=float)
    t = np.asarray(t_s, dtype=float)
    valid, n_nan, n_quality = _validity(x, quality)
    index = np.flatnonzero(valid)
    rows = x[index]
    t2, spe = model.t2(rows), model.spe(rows)
    exceed = (t2 > model.t2_limit) | (spe > model.spe_limit)
    events = tuple(
        _event(model, span, rows, (t2, spe), (index, t[index]))
        for span in _spans(exceed, config)
    )
    return ScanResult(
        events=events, n_valid=len(index), n_skipped=n_nan + n_quality,
        skipped_reasons={"nan": n_nan, "quality": n_quality},
    )
