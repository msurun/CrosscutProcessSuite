"""Candidates of exp15 for the ranked stiction suspicion: window at high noise, epoch folding.

variant "base" = the shipped package; "c1a" = spectral-peak period, regularity normalised by the
lag-1 autocorrelation, window searched on OUT and PV; "c1b" = c1a plus the curve-fit index on the
epoch-folded waveform (all cycles on one phase grid, the noise averaged down by the cycle count).
"""

from __future__ import annotations

import numpy as np
from crosscut_loops import stiction_suspicion as ss
from crosscut_loops.stiction_curvefit import _detrend

ARRAY = ss.ARRAY
FOLD_BINS = 64  # phase bins of the folded waveform
MIN_FOLDED_HALF_SAMPLES = 3.0  # samples per half-cycle the folded index accepts (many cycles)
MIN_FOLDED_CYCLES = 10
VARIANTS = ("base", "c1a", "c1b", "c2a", "c2b", "c3a", "c3b", "c4a", "c4b", "c5a", "c5b")
PROMINENCE_MIN = (
    36.5  # pooled 97th percentile of noise-only records (calib_prominence.py, synthetic)
)
PERIOD_AGREEMENT = 0.05  # OUT and PV peaks must agree within 5 % in period
PROMINENCE_PAIR = 11.7  # pooled 99th percentile of independent noise pairs (calib_prominence.py)
PROMINENCE_WHOLE = 20.0  # 99th percentile of one whole-record noise peak (calib_whole.py)
HORCH_WEIGHT_C5B = 0.25
NEIGHBOURHOOD = (0.5, 2.0)  # band around the peak (in frequency) that sets the noise floor


def spectral_period(x: ARRAY) -> float | None:
    """Period in samples from the strongest spectral peak with at least MIN_CYCLES cycles."""
    n = x.size
    pad = 8 * n
    power = np.abs(np.fft.rfft(x * np.hanning(n), pad)) ** 2
    k_min = int(ss.MIN_CYCLES * 8)  # bin index in the padded spectrum = cycles * 8
    k_max = pad // 4
    if k_min >= k_max:
        return None
    k = k_min + int(np.argmax(power[k_min:k_max]))
    a, b, c = np.log(power[k - 1 : k + 2] + ss.EPS)
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    return float(pad / (k + shift))


def regularity_lag1(x: ARRAY, period: float) -> float:
    """Autocorrelation at one (fractional) period divided by the lag-1 value (white noise only
    inflates lag 0, so lag 1 is the noise-robust reference)."""
    spectrum = np.fft.rfft(x, 2 * x.size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum))[: x.size]
    lag = period
    if lag >= x.size - 1 or acf[1] <= 0:
        return 0.0
    value = np.interp(lag, np.arange(x.size), acf)
    return float(value / acf[1])


def try_segment(sp: ARRAY, signals: tuple[ARRAY, ARRAY], a: int, b: int) -> ss.Window | None:
    """Best Window of the segment over the given signals (OUT and PV), or None."""
    best = None
    for sig in signals:
        x = _detrend(sig[a:b])
        period = spectral_period(x)
        if period is None or (b - a) / period < ss.MIN_CYCLES:
            continue
        reg = regularity_lag1(x, period)
        quiet = np.ptp(sp[a:b]) <= ss.MAX_SP_SWING * max(np.ptp(_detrend(signals[1][a:b])), ss.EPS)
        if reg >= ss.MIN_REGULARITY and quiet and (best is None or reg > best.regularity):
            best = ss.Window(a, b, period, reg)
    return best


def find_window(sp: ARRAY, pv: ARRAY, out: ARRAY) -> ss.Window | None:
    """Best segment of the 15 candidates (longer wins near ties), as in the package."""
    n = pv.size
    found = []
    for k in ss.SEGMENT_SPLITS:
        for i in range(k):
            w = try_segment(sp, (out, pv), i * n // k, (i + 1) * n // k)
            if w is not None:
                found.append((w.regularity + 0.05 * np.log2(w.stop - w.start), w))
    return max(found, key=lambda f: f[0])[1] if found else None


def fold(x: ARRAY, period: float) -> tuple[ARRAY, float]:
    """Epoch-folded waveform on FOLD_BINS phase bins and the noise variance left in each bin."""
    bins = np.minimum(((np.arange(x.size) / period) % 1.0 * FOLD_BINS).astype(int), FOLD_BINS - 1)
    count = np.bincount(bins, minlength=FOLD_BINS).astype(float)
    wave = np.bincount(bins, weights=x, minlength=FOLD_BINS)
    filled = count > 0
    wave[filled] /= count[filled]
    idx = np.arange(FOLD_BINS)
    wave = np.interp(idx, idx[filled], wave[filled], period=FOLD_BINS)
    residual = x - wave[bins]
    return wave - wave.mean(), float(np.var(residual) / max(np.mean(count[filled]), 1.0))


def folded_index(x: ARRAY, period: float) -> float | None:
    """Curve-fit index of the epoch-folded waveform (median over its two half-cycles)."""
    if period / 2.0 < MIN_FOLDED_HALF_SAMPLES or x.size / period < MIN_FOLDED_CYCLES:
        return None
    wave, noise = fold(x, period)
    up = np.flatnonzero((wave[:-1] < 0) & (wave[1:] >= 0))
    if up.size == 0:
        return None
    wave = np.roll(wave, -int(up[0] + 1))
    down = np.flatnonzero((wave[:-1] >= 0) & (wave[1:] < 0))
    if down.size == 0:
        return None
    cut = int(down[0] + 1)
    halves = [wave[:cut], wave[cut:]]
    if min(h.size for h in halves) < 6:
        return None
    return float(np.median([ss._corrected_index(abs_sign(h), noise) for h in halves]))


def abs_sign(half: ARRAY) -> ARRAY:
    """A half-cycle with its sign flipped to positive (the fits expect a positive hump)."""
    return half if half.mean() >= 0 else -half


def rank(rec: ss.Record, w: ss.Window, dt_s: float, variant: str) -> ss.SuspicionResult:
    """Tests on the window; c1b uses the folded curve-fit index when the base index refuses."""
    sl = slice(w.start, w.stop)
    sig = (rec.pv if rec.kind == "L" else rec.out)[sl]
    he, why = ss._he_index(sig)
    if variant in ("c1b", "c2b", "c3b", "c4b"):
        folded = folded_index(_detrend(sig), w.period)
        he = folded if folded is not None else he
    horch = None
    if rec.kind != "L":
        horch = ss._calibrated(ss._horch_oddness(rec.out[sl], rec.pv[sl], w.period))
    parts = [p for p in (horch, he) if p is not None]
    if not parts:
        return ss.SuspicionResult(None, "not_ranked", he, horch, w.period * dt_s, why)
    score = float(np.mean(parts))
    return ss.SuspicionResult(score, ss._advice(score), he, horch, w.period * dt_s, "")


def suspicion15(
    sp: ARRAY, pv: ARRAY, out: ARRAY, dt_s: float, kind: str = "F", variant: str = "base"
) -> ss.SuspicionResult:
    """The suspicion with the chosen variant (base = shipped package function)."""
    if variant == "base":
        return ss.stiction_suspicion(sp, pv, out, dt_s, kind)
    arrays = tuple(np.asarray(a, dtype=float) for a in (sp, pv, out))
    ss._validate(arrays, dt_s, kind)  # type: ignore[arg-type]
    if not all(np.all(np.isfinite(a)) for a in arrays) or arrays[0].size < 8 * ss.MIN_CYCLES:
        return ss.SuspicionResult(None, "not_ranked", None, None, None, "bad input")
    finder = {
        "c2a": find_window_p,
        "c2b": find_window_p,
        "c3a": find_window_c3,
        "c3b": find_window_c3,
    }.get(variant, find_window)
    if variant in ("c5a", "c5b"):
        return suspicion_c5(
            ss.Record(arrays[0], arrays[1], arrays[2], kind),
            dt_s,
            HORCH_WEIGHT_C5B if variant == "c5b" else 0.0,
        )
    if variant in ("c4a", "c4b"):
        finder = find_window_p
    w = finder(arrays[0], arrays[1], arrays[2])
    if w is None and variant in ("c4a", "c4b"):
        return whole_record_result(ss.Record(arrays[0], arrays[1], arrays[2], kind), dt_s)
    if w is None:
        return ss.SuspicionResult(None, "not_ranked", None, None, None, "no window")
    return rank(ss.Record(arrays[0], arrays[1], arrays[2], kind), w, dt_s, variant)


def peak_prominence(x: ARRAY) -> tuple[float, float] | None:
    """(period in samples, prominence) of the strongest spectral peak with >= MIN_CYCLES cycles.

    Prominence = peak power / median power in the band 0.5-2 times the peak frequency, with the
    peak itself (+-3 bins) left out: a red-noise spectrum is lifted around the peak as well, so a
    random wander does not look prominent, while a limit cycle stands out of its neighbourhood.
    """
    n = x.size
    pad = 4 * n
    power = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(n), pad)) ** 2
    k_min, k_max = int(ss.MIN_CYCLES * 4), pad // 4
    if k_min >= k_max - 8:
        return None
    k = k_min + int(np.argmax(power[k_min:k_max]))
    lo, hi = int(NEIGHBOURHOOD[0] * k), min(int(NEIGHBOURHOOD[1] * k), power.size - 1)
    around = np.r_[power[lo : k - 3], power[k + 4 : hi]]
    if around.size < 8 or np.median(around) <= 0:
        return None
    a, b, c = np.log(power[k - 1 : k + 2] + ss.EPS)
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    return float(pad / (k + shift)), float(power[k] / np.median(around))


def try_segment_p(sp: ARRAY, signals: tuple[ARRAY, ARRAY], a: int, b: int) -> ss.Window | None:
    """The segment as a Window (regularity field = prominence) if a peak is significant."""
    best = None
    for sig in signals:
        x = _detrend(sig[a:b])
        found = peak_prominence(x)
        if found is None or (b - a) / found[0] < ss.MIN_CYCLES or found[1] < PROMINENCE_MIN:
            continue
        quiet = np.ptp(sp[a:b]) <= ss.MAX_SP_SWING * max(np.ptp(_detrend(signals[1][a:b])), ss.EPS)
        if quiet and (best is None or found[1] > best.regularity):
            best = ss.Window(a, b, found[0], found[1])
    return best


def find_window_p(sp: ARRAY, pv: ARRAY, out: ARRAY) -> ss.Window | None:
    """Longest segment with a significant peak; ties (same length) go to the higher prominence."""
    n = pv.size
    found = []
    for k in ss.SEGMENT_SPLITS:
        for i in range(k):
            w = try_segment_p(sp, (out, pv), i * n // k, (i + 1) * n // k)
            if w is not None:
                found.append(((w.stop - w.start, w.regularity), w))
    return max(found, key=lambda f: f[0])[1] if found else None


def try_segment_c3(sp: ARRAY, signals: tuple[ARRAY, ARRAY], a: int, b: int) -> ss.Window | None:
    """Window if either signal has a very prominent peak or both agree on a moderate one."""
    out_x, pv_x = _detrend(signals[0][a:b]), _detrend(signals[1][a:b])
    po, pp = peak_prominence(out_x), peak_prominence(pv_x)
    quiet = np.ptp(sp[a:b]) <= ss.MAX_SP_SWING * max(np.ptp(pv_x), ss.EPS)
    if not quiet:
        return None
    cands = [f for f in (po, pp) if f is not None and f[1] >= PROMINENCE_MIN]
    if po is not None and pp is not None and abs(po[0] / pp[0] - 1.0) <= PERIOD_AGREEMENT:
        if min(po[1], pp[1]) >= PROMINENCE_PAIR:
            cands.append((0.5 * (po[0] + pp[0]), min(po[1], pp[1])))
    cands = [f for f in cands if (b - a) / f[0] >= ss.MIN_CYCLES]
    if not cands:
        return None
    best = max(cands, key=lambda f: f[1])
    return ss.Window(a, b, best[0], best[1])


def find_window_c3(sp: ARRAY, pv: ARRAY, out: ARRAY) -> ss.Window | None:
    """Longest segment accepted by the coincidence gate; ties go to the higher prominence."""
    n = pv.size
    found = []
    for k in ss.SEGMENT_SPLITS:
        for i in range(k):
            w = try_segment_c3(sp, (out, pv), i * n // k, (i + 1) * n // k)
            if w is not None:
                found.append(((w.stop - w.start, w.regularity), w))
    return max(found, key=lambda f: f[0])[1] if found else None


def whole_record_result(rec: ss.Record, dt_s: float) -> ss.SuspicionResult:
    """No window: the curve-fit index on the whole record is the only test (no Horch)."""
    sig = rec.pv if rec.kind == "L" else rec.out
    he, why = ss._he_index(sig)
    if he is None:
        return ss.SuspicionResult(None, "not_ranked", None, None, None, why)
    return ss.SuspicionResult(he, ss._advice(he), he, None, None, "whole record, no window")


def c5_segment(sp: ARRAY, pv: ARRAY, out: ARRAY, sig: ARRAY) -> tuple[slice, float] | None:
    """Window by prominence, else the whole record if its single peak passes the whole gate."""
    w = find_window_p(sp, pv, out)
    if w is not None:
        return slice(w.start, w.stop), w.period
    found = peak_prominence(_detrend(sig))
    quiet = np.ptp(sp) <= ss.MAX_SP_SWING * max(np.ptp(_detrend(pv)), ss.EPS)
    if found and found[1] >= PROMINENCE_WHOLE and sig.size / found[0] >= ss.MIN_CYCLES and quiet:
        return slice(0, sig.size), found[0]
    return None


def suspicion_c5(rec: ss.Record, dt_s: float, horch_weight: float) -> ss.SuspicionResult:
    """Score = curve-fit index of the epoch-folded waveform (OUT, or PV for level loops)."""
    sig = rec.pv if rec.kind == "L" else rec.out
    seg = c5_segment(rec.sp, rec.pv, rec.out, sig)
    if seg is None:
        return ss.SuspicionResult(
            None, "not_ranked", None, None, None, "no significant oscillation"
        )
    sl, period = seg
    he = folded_index(_detrend(sig[sl]), period)
    if he is None:
        he, _ = ss._he_index(sig[sl])
    if he is None:
        return ss.SuspicionResult(None, "not_ranked", None, None, period * dt_s, "no usable shape")
    horch = None
    if rec.kind != "L" and horch_weight > 0:
        horch = ss._calibrated(ss._horch_oddness(rec.out[sl], rec.pv[sl], period))
    score = he if horch is None else (1 - horch_weight) * he + horch_weight * horch
    return ss.SuspicionResult(float(score), ss._advice(score), he, horch, period * dt_s, "")
