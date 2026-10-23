"""Event detection on T2 and SPE: runs of limit exceedances become anomaly events.

The scan works on the sequence of valid rows only (finite values, quality 0).
Invalid rows are counted, never imputed, and neither extend nor break a run.
A second rule flags a sensor that is exactly constant while others move (stuck).
Advisory only: no plant writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from crosscut_anomaly.config import AnomalyConfig, AnomalyConfigError
from crosscut_anomaly.pca_model import PcaModel, augment_lags

TOP_TAGS = 3
MIN_MOVING_OTHERS = 3


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
    kind: str = "pca"
    stuck_tag: str | None = None


@dataclass(frozen=True)
class ScanResult:
    """Events of one scan plus the valid / skipped row counts."""

    events: tuple[AnomalyEvent, ...]
    n_valid: int
    n_skipped: int
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    limit_methods: dict[str, str] = field(default_factory=dict)

    @property
    def n_pca_events(self) -> int:
        """Number of events of kind ``pca``."""
        return sum(e.kind == "pca" for e in self.events)

    @property
    def n_stuck_events(self) -> int:
        """Number of events of kind ``stuck``."""
        return sum(e.kind == "stuck" for e in self.events)


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


def _bad_quality(quality: Sequence[float] | np.ndarray | None, n: int, p: int) -> np.ndarray:
    """Per-row bad-quality mask from one value per row (n,) or per tag (n, p).

    Raises:
        ValueError: for any other shape (a 2-D array must be exactly (n, p)).
    """
    if quality is None:
        return np.zeros(n, dtype=bool)
    q = np.asarray(quality, dtype=float)
    if q.shape == (n,):
        return np.asarray(q != 0)
    if q.shape == (n, p):
        return np.asarray((q != 0).any(axis=1))
    raise ValueError(f"quality must have shape ({n},) or ({n}, {p}), got {q.shape}")


def _validity(
    x: np.ndarray, quality: Sequence[float] | np.ndarray | None
) -> tuple[np.ndarray, int, int]:
    """Valid mask plus the rows skipped as non-finite (reason 'nan') and for quality."""
    non_finite = ~np.isfinite(x).all(axis=1)
    bad_q = _bad_quality(quality, x.shape[0], x.shape[1])
    return ~(non_finite | bad_q), int(non_finite.sum()), int((bad_q & ~non_finite).sum())


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


def _stuck_runs(col: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """(first, last) positions of runs of exactly equal values of at least ``min_len``."""
    cuts = np.flatnonzero(col[1:] != col[:-1]) + 1
    starts = np.concatenate(([0], cuts))
    ends = np.concatenate((cuts - 1, [len(col) - 1]))
    return [(int(a), int(b)) for a, b in zip(starts, ends, strict=True) if b - a + 1 >= min_len]


def _others_moving(rows: np.ndarray, tag: int, first: int, count: int) -> bool:
    """True if at least 3 other tags are not constant over ``count`` samples from ``first``."""
    window = rows[first : first + count]
    moving = np.ptp(window, axis=0) > 0
    return int(moving.sum() - bool(moving[tag])) >= MIN_MOVING_OTHERS


def _stuck_event(
    name: str, span: tuple[int, int], rows_n: int, orig: tuple[np.ndarray, np.ndarray]
) -> AnomalyEvent:
    """Event for a stuck run over valid positions ``span``; open if the data ends in it."""
    first, last = span
    index, t_valid = orig
    return AnomalyEvent(
        start_index=int(index[first]), end_index=int(index[last]),
        start_s=float(t_valid[first]), end_s=float(t_valid[last]),
        closed=last < rows_n - 1, peak_t2=float("nan"), peak_spe=float("nan"),
        peak_index=int(index[first]), top_spe_tags=(name,), top_t2_tags=(name,),
        exceeded="stuck", n_samples=last - first + 1, kind="stuck", stuck_tag=name,
    )


def _stuck_events(
    tags: Sequence[str], rows: np.ndarray, orig: tuple[np.ndarray, np.ndarray], count: int
) -> list[AnomalyEvent]:
    """Stuck-sensor events on the valid rows (finite, quality 0); ``count`` >= 3 samples."""
    events: list[AnomalyEvent] = []
    if len(rows) < count:
        return events
    for j, name in enumerate(tags):
        for span in _stuck_runs(rows[:, j], count):
            if _others_moving(rows, j, span[0], count):
                events.append(_stuck_event(name, span, len(rows), orig))
    return events


def _pca_events(
    model: PcaModel, rows: np.ndarray, orig: tuple[np.ndarray, np.ndarray],
    config: AnomalyConfig,
) -> tuple[AnomalyEvent, ...]:
    """PCA events on the valid rows of the (lag-augmented) matrix."""
    t2, spe = model.t2(rows), model.spe(rows)
    exceed = (t2 > model.t2_limit) | (spe > model.spe_limit)
    return tuple(_event(model, span, rows, (t2, spe), orig) for span in _spans(exceed, config))


def scan(
    model: PcaModel,
    t_s: Sequence[float] | np.ndarray,
    x: np.ndarray,
    quality: Sequence[float] | np.ndarray | None = None,
    config: AnomalyConfig | None = None,
) -> ScanResult:
    """Scan a raw record (samples by tags) and return its anomaly events.

    ``quality`` is one value per row (n,) or one per tag (n, p); a row is invalid if any
    value != 0. Rows with NaN or +-inf are invalid too and counted under
    ``skipped_reasons['nan']`` (the key means non-finite). With a dynamic model
    (``model.dynamic_lags`` > 0) the lag-augmented matrix is built here and a row is
    valid only if all its lagged source rows are; rows lost to missing history or to
    an invalid lagged row are counted under ``skipped_reasons['lag']``. If
    ``config.stuck_samples`` > 0 the stuck-sensor rule adds events of kind ``stuck``;
    events are sorted by start (PCA first on ties).

    Raises:
        AnomalyConfigError: if ``config`` is missing.
        ValueError: if ``quality`` has a shape other than (n,) or (n, p).
    """
    if config is None:
        raise AnomalyConfigError("config: required")
    x = np.asarray(x, dtype=float)
    t = np.asarray(t_s, dtype=float)
    valid, n_nan, n_quality = _validity(x, quality)
    index = np.flatnonzero(valid)
    aug = augment_lags(np.where(valid[:, None], x, np.nan), model.dynamic_lags)
    a_index = np.flatnonzero(np.isfinite(aug).all(axis=1))
    events = list(_pca_events(model, aug[a_index], (a_index, t[a_index]), config))
    if config.stuck_samples:
        events += _stuck_events(model.monitored_tags, x[index], (index, t[index]),
                                config.stuck_samples)
    events.sort(key=lambda e: e.start_index)
    n_lag = len(index) - len(a_index)
    reasons = {"nan": n_nan, "quality": n_quality, **({"lag": n_lag} if model.dynamic_lags else {})}
    return ScanResult(
        events=tuple(events), n_valid=len(a_index), n_skipped=n_nan + n_quality + n_lag,
        skipped_reasons=reasons,
        limit_methods={"t2": "hotelling_f", "spe": model.spe_limit_method},
    )
