"""Hagglund (1999) idle index for closed-loop control-loop records.

The idle index measures whether the controller output and the measurement move together
during a recovery (sluggish) or in opposite directions (fast). Our additions to the
published statistic: a noise gate, a stride from the error autocorrelation time, and a
gain-sign estimate from the output drift.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_SAMPLES = 200  # below this the ACF and the noise estimate are meaningless
MIN_COUNTED = 30  # counted increment pairs needed for a finite index
GATE_SIGMAS = 2.0  # noise gate: K times sqrt(2) * sigma of an increment
MAD_TO_STD = 1.4826  # median absolute deviation to standard deviation, normal law
STRIDE_DIVISOR = 4  # stride L = max(1, round(q / STRIDE_DIVISOR)); q is the ACF lag
MAX_LAG_DIVISOR = 4  # ACF lags searched for q, as a share of the record length


@dataclass(frozen=True)
class IdleIndex:
    """Result of the idle index computation for one closed-loop record.

    Attributes:
        value: The idle index in [-1, 1], or None when it could not be computed.
        gain_sign: Estimated process-gain sign (+1 or -1), or None if unknown.
        counted: Number of increment pairs that passed the noise gate.
        stride: Stride L in samples used for the increments.
        reason: Empty when value is set; otherwise a short explanation.
    """

    value: float | None
    gain_sign: int | None
    counted: int
    stride: int
    reason: str


def idle_index(
    pv: np.ndarray, sp: np.ndarray, out: np.ndarray, dt_s: float
) -> IdleIndex:
    """Compute the Hagglund (1999) idle index for one closed-loop record.

    Args:
        pv: Measured process variable, 1-D, equally spaced.
        sp: Setpoint, same length as pv.
        out: Controller output, same length as pv.
        dt_s: Sampling interval in seconds (must be positive; not used otherwise).

    Returns:
        IdleIndex with the value, gain sign, counted pairs, stride and reason.

    Raises:
        ValueError: if a signal contains NaN, lengths differ, or dt_s is not positive.
    """
    pv, sp, out = _validate(pv, sp, out, dt_s)
    n = pv.size
    if n < MIN_SAMPLES:
        return IdleIndex(None, None, 0, 1, "too short")

    stride = _stride(pv, sp)
    gain_sign = _gain_sign(pv, sp, out)
    if gain_sign == 0:
        return IdleIndex(None, None, 0, stride, "gain sign unknown")

    n_pos, n_neg = _count_pairs(pv, sp, out, stride)
    counted = n_pos + n_neg
    if counted < MIN_COUNTED:
        return IdleIndex(None, gain_sign, counted, stride, "too little movement")

    value = gain_sign * (n_pos - n_neg) / counted
    return IdleIndex(float(value), gain_sign, counted, stride, "")


def _validate(
    pv: np.ndarray, sp: np.ndarray, out: np.ndarray, dt_s: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Check shape, NaN content and dt_s, and return the arrays as float."""
    pv = np.asarray(pv, dtype=float)
    sp = np.asarray(sp, dtype=float)
    out = np.asarray(out, dtype=float)
    if not (pv.size == sp.size == out.size):
        raise ValueError("pv, sp and out must have the same length")
    if np.any(np.isnan(pv)) or np.any(np.isnan(sp)) or np.any(np.isnan(out)):
        raise ValueError("pv, sp and out must not contain NaN")
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    return pv, sp, out


def _stride(pv: np.ndarray, sp: np.ndarray) -> int:
    """Stride L in samples from the error autocorrelation time q.

    q = first lag where the biased ACF of the linearly detrended error e = sp - pv is
    <= 0, searched up to n // 4. L = max(1, round(q / 4)). The ACF is computed by FFT
    with zero padding to at least 2n to avoid circular wrap-around, then divided by lag 0.
    """
    error = _detrend_linear(sp - pv)
    n = error.size
    nfft = 1 << (n - 1).bit_length()  # next power of two, for a fast FFT
    nfft = max(nfft, 2 * n)
    spectrum = np.fft.rfft(error, n=nfft)
    acf_full = np.fft.irfft(spectrum * np.conjugate(spectrum), n=nfft)
    max_lag = max(1, n // MAX_LAG_DIVISOR)
    acf = acf_full[: max_lag + 1] / acf_full[0]  # biased, normalised by lag 0

    nonpositive = np.flatnonzero(acf <= 0.0)
    q = int(nonpositive[0]) if len(nonpositive) else max_lag
    return max(1, int(round(q / STRIDE_DIVISOR)))


def _detrend_linear(samples: np.ndarray) -> np.ndarray:
    """Remove mean and least-squares linear trend from a 1-D signal."""
    t = np.arange(samples.size, dtype=float)
    slope, intercept = np.polyfit(t, samples, 1)
    return np.asarray(samples - (slope * t + intercept), dtype=float)


def _noise_sigma(samples: np.ndarray) -> float:
    """White-noise standard deviation from the second-difference MAD estimate.

    For white noise the second difference x[k+2] - 2 x[k+1] + x[k] has variance
    6 sigma^2, so sigma = 1.4826 * median(|second difference|) / sqrt(6). Smooth
    motion contributes little to the second difference.
    """
    second_difference = samples[2:] - 2.0 * samples[1:-1] + samples[:-2]
    mad = float(np.median(np.abs(second_difference)))
    return float(MAD_TO_STD * mad / np.sqrt(6.0))


def _steady_sp_mask(sp: np.ndarray, stride: int) -> np.ndarray:
    """True at k when sp[k..k+stride] are all equal (a load recovery, not a setpoint step).

    Uses a sliding window over sp; a window is steady when its max minus min is 0.
    The returned mask has length n - stride, matching the increment index range.
    """
    windows = np.lib.stride_tricks.sliding_window_view(sp, stride + 1)
    return np.asarray((windows.max(axis=1) - windows.min(axis=1)) == 0.0)


def _gain_sign(pv: np.ndarray, sp: np.ndarray, out: np.ndarray) -> int:
    """Process-gain sign from the output drift against the error, as +1, -1 or 0.

    With integral action the output moves in the direction of the error times the
    process-gain sign. s = sign(sum (out[k+1] - out[k]) * e[k]) over samples where the
    setpoint is locally constant. Returns 0 when that sum is exactly 0.
    """
    error = sp - pv
    steady = sp[1:] == sp[:-1]
    drift = (out[1:] - out[:-1])[steady]
    # Midpoint error (exp22 amendment 1): the proportional part Kc * (e[k+1] - e[k]) times
    # (e[k] + e[k+1]) / 2 telescopes to zero, so measurement noise cannot outweigh the
    # integral part Kc * dt / Ti * e^2, whose sign is the process-gain sign.
    midpoint = 0.5 * (error[:-1] + error[1:])
    contribution = float(np.sum(drift * midpoint[steady]))
    if contribution > 0.0:
        return 1
    if contribution < 0.0:
        return -1
    return 0


def _count_pairs(
    pv: np.ndarray, sp: np.ndarray, out: np.ndarray, stride: int
) -> tuple[int, int]:
    """Count gated increment pairs with du * dy > 0 (n_pos) and with du * dy < 0 (n_neg).

    Increments are dy[k] = pv[k+L] - pv[k] and du[k] = out[k+L] - out[k] for
    k = 0..n-L-1, kept only where sp[k..k+L] is steady. A pair counts when
    |dy| > GATE_SIGMAS * sqrt(2) * sigma_pv and |du| > GATE_SIGMAS * sqrt(2) * sigma_out,
    and both increments are non-zero. sqrt(2) accounts for the difference of two noisy
    samples.
    """
    threshold_pv = GATE_SIGMAS * np.sqrt(2.0) * _noise_sigma(pv)
    threshold_out = GATE_SIGMAS * np.sqrt(2.0) * _noise_sigma(out)
    dy = pv[stride:] - pv[:-stride]
    du = out[stride:] - out[:-stride]
    steady = _steady_sp_mask(sp, stride)

    gated = (
        steady
        & (np.abs(dy) > threshold_pv)
        & (np.abs(du) > threshold_out)
        & (dy != 0.0)
        & (du != 0.0)
    )
    product = du[gated] * dy[gated]
    n_pos = int(np.count_nonzero(product > 0.0))
    n_neg = int(np.count_nonzero(product < 0.0))
    return n_pos, n_neg
