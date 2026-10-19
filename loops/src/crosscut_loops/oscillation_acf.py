"""Parameter-free oscillation detection for control-loop error signals.

Implements the method of Thornhill, Huang & Zhang (2003), "Detection of multiple
oscillations in control loops", J. Process Control 13. The threshold r > 1 is the
published default, not tuned on our data; the noise-band hysteresis is our addition.
"""

from dataclasses import dataclass

import numpy as np

REGULARITY_THRESHOLD = 1.0  # r > 1: regular oscillation (Thornhill et al. 2003)
MAX_ZERO_CROSSINGS = 11  # use at most the first 11 ACF zero crossings (10 intervals)
MIN_ZERO_CROSSINGS = 7  # 5 period estimates; with 5, AR(1) phi=0.99 drift passed 21 % of runs
MIN_SAMPLES = 64
NOISE_BAND_Z = 1.96  # 95 % band of a white-noise ACF is +-1.96 / sqrt(n)
FLAT_RELATIVE_STD = 1e-12  # detrended std below this share of the signal scale is rounding only
BAND_BARTLETT = "bartlett"
BAND_WHITE = "white"
BAND_BARTLETT_LAG = "bartlett_lag"  # Bartlett variance with n - k pairs at lag k (exp21)


@dataclass(frozen=True)
class AcfConfig:
    """Detector variant; the defaults are the shipped detector (exp20/exp21 compare variants)."""

    band: str = BAND_BARTLETT  # BAND_BARTLETT, BAND_BARTLETT_LAG or BAND_WHITE (1.96 / sqrt(n))
    min_crossings: int = MIN_ZERO_CROSSINGS
    max_lag_fraction: float = 0.5  # ACF lags used, as a share of the record length
    unbiased: bool = False  # divide the lag-k sum by n - k instead of n
    peak_z: float = 0.0  # 0 = off; else the first lobe after lag 0 must peak above peak_z sigma

    def __post_init__(self) -> None:
        """Reject lag ranges that would divide by n - k = 0 or read past the record."""
        if not 0.0 < self.max_lag_fraction < 1.0:
            raise ValueError("max_lag_fraction must be between 0 and 1 (exclusive)")
        if self.peak_z < 0.0:
            raise ValueError("peak_z must be non-negative")


SHIPPED = AcfConfig()


@dataclass(frozen=True)
class AcfOscillation:
    """Result of ACF regularity analysis for an error signal.

    Attributes:
        regular: True when regularity exceeds the published threshold.
        period_s: Mean oscillation period in seconds when regular, else None.
        regularity: The r statistic, or None when it could not be computed.
        reason: Empty when regular; otherwise a short explanation.
    """

    regular: bool
    period_s: float | None
    regularity: float | None
    reason: str


def acf_regularity(error: np.ndarray, dt_s: float, config: AcfConfig = SHIPPED) -> AcfOscillation:
    """Detect regular oscillation in a detrended control-loop error signal.

    Args:
        error: 1-D array of error samples, equally spaced in time.
        dt_s: Sampling interval in seconds.
        config: Detector variant; the default is the shipped one.

    Returns:
        AcfOscillation with regularity, period and status.

    Raises:
        ValueError: if error contains NaN or dt_s is not positive.
    """
    _validate_inputs(error, dt_s)
    if np.asarray(error).size < MIN_SAMPLES:
        return AcfOscillation(False, None, None, "too short")
    samples = _detrend(error)
    if _is_flat(samples, error):
        return AcfOscillation(False, None, None, "flat signal")

    acf = _autocorrelation(samples, config)
    sigma = _noise_sigma(acf, samples.size, config)
    zero_crossings = _zero_crossings(acf, NOISE_BAND_Z * sigma)

    if len(zero_crossings) < config.min_crossings:
        return AcfOscillation(False, None, None, "too few ACF zero crossings")

    regularity, period_samples = _regularity(zero_crossings)
    if regularity <= REGULARITY_THRESHOLD:
        return AcfOscillation(False, None, float(regularity), f"irregular (r={regularity:.2f})")
    if config.peak_z > 0.0 and not _peak_is_strong(acf, sigma, zero_crossings, config.peak_z):
        return AcfOscillation(False, None, float(regularity), "weak ACF peak")
    return AcfOscillation(True, float(period_samples * dt_s), float(regularity), "")


def _validate_inputs(error: np.ndarray, dt_s: float) -> None:
    """Check NaN content and sampling interval."""
    if np.any(np.isnan(error)):
        raise ValueError("error contains NaN")
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")


def _detrend(error: np.ndarray) -> np.ndarray:
    """Remove mean and least-squares linear trend from the signal."""
    samples = np.asarray(error, dtype=float)
    sample_count = samples.size
    sample_index = np.arange(sample_count, dtype=float)
    coefficients = np.polyfit(sample_index, samples, 1)
    return samples - np.polyval(coefficients, sample_index)


def _is_flat(samples: np.ndarray, error: np.ndarray) -> bool:
    """True when the detrended residual is only rounding noise of the original signal.

    The scale is the largest |error|, but at least 1, so a tiny signal is not called noisy.
    """
    scale = max(float(np.max(np.abs(error))), 1.0)
    return float(np.std(samples)) <= FLAT_RELATIVE_STD * scale


def _autocorrelation(samples: np.ndarray, config: AcfConfig) -> np.ndarray:
    """Autocorrelation via FFT with zero padding, up to lag max_lag_fraction * n.

    The padding length avoids circular wrap-around. Late lags rest on few sample pairs, so
    they are cut off (shipped: n // 2). The unbiased variant divides lag k by n - k.
    """
    sample_count = samples.size
    nfft = 1 << (sample_count - 1).bit_length()
    nfft = max(nfft, 2 * sample_count)
    spectrum = np.fft.rfft(samples, n=nfft)
    acf_full = np.fft.irfft(spectrum * np.conjugate(spectrum), n=nfft)
    acf = acf_full[: int(config.max_lag_fraction * sample_count) + 1]
    if config.unbiased:
        acf = acf * sample_count / (sample_count - np.arange(acf.size))
    return np.asarray(acf / acf[0], dtype=float)


def _noise_sigma(acf: np.ndarray, n_samples: int, config: AcfConfig) -> np.ndarray:
    """Standard deviation of the ACF estimation noise at every lag (one value per lag).

    Bartlett's formula for an MA(q) process (Box and Jenkins, see docs/PROVENANCE.md),
    var(r_k) = (1 + 2 * sum r_j^2) / n, with q the lag before the first zero crossing. A
    white-noise band (q = 0) was too narrow for correlated disturbances: AR(1) with phi = 0.9
    passed as regular in 23 of 100 runs.
    BAND_BARTLETT_LAG divides by the n - k sample pairs at lag k instead of n, the variance of
    the unbiased estimator; it widens the band where few pairs remain.
    """
    if config.band == BAND_WHITE:
        return np.full(acf.size, 1.0 / np.sqrt(n_samples))
    nonpositive = np.flatnonzero(acf <= 0.0)
    # First lag with r <= 0; the Bartlett sum below runs over lags 1..q with q = ma_order - 1.
    ma_order = int(nonpositive[0]) if len(nonpositive) else len(acf)
    bartlett_sum = 1.0 + 2.0 * float(np.sum(acf[1:ma_order] ** 2))
    pairs = np.full(acf.size, float(n_samples))
    if config.band == BAND_BARTLETT_LAG:
        pairs = n_samples - np.arange(acf.size, dtype=float)
    return np.sqrt(bartlett_sum / pairs)


def _peak_is_strong(
    acf: np.ndarray, sigma: np.ndarray, crossings: np.ndarray, peak_z: float
) -> bool:
    """True when the first positive lobe after lag 0 peaks above peak_z noise sigmas (exp21).

    That lobe lies between the second and third crossing, centred near one period. A real
    cycle gives a wide lobe far outside the band; chance exceedances of fast noise do not.
    """
    if len(crossings) < 3:  # no complete first lobe: nothing to confirm, so no strong peak
        return False
    start, stop = int(np.ceil(crossings[1])), int(np.floor(crossings[2])) + 1
    lag = start + int(np.argmax(acf[start:stop]))
    return bool(acf[lag] > peak_z * sigma[lag])


def _zero_crossings(acf: np.ndarray, band: np.ndarray) -> np.ndarray:
    """Fractional lags where the ACF passes from one side of the noise band to the other.

    Our addition to Thornhill et al.: a crossing counts only when the ACF leaves +-band on
    both sides of it (hysteresis). Plain sign changes let white noise, whose ACF crosses zero
    every few lags almost evenly, pass r > 1 for 5 of 10 seeds, and let estimation noise add
    spurious double crossings to a real cycle. Crossings inside one passage are averaged.
    """
    outside = np.flatnonzero(np.abs(acf) > band)  # band: half-width per lag
    side = acf[outside] > 0
    passages = np.flatnonzero(side[1:] != side[:-1])
    crossings = [
        _passage_lag(acf, int(outside[passage]), int(outside[passage + 1]))
        for passage in passages.tolist()
    ]
    return np.asarray(crossings[:MAX_ZERO_CROSSINGS], dtype=float)


def _passage_lag(acf: np.ndarray, start: int, stop: int) -> float:
    """Mean of the interpolated sign changes of the ACF between lags start and stop."""
    k = start + np.flatnonzero((acf[start:stop] > 0) != (acf[start + 1 : stop + 1] > 0))
    return float(np.mean(k + acf[k] / (acf[k] - acf[k + 1])))


def _regularity(zero_crossings: np.ndarray) -> tuple[float, float]:
    """Compute regularity r and mean period from zero crossing lags.

    Period estimates are differences of crossings two apart; each spans
    one full cycle.
    """
    periods = zero_crossings[2:] - zero_crossings[:-2]
    mean_period = float(np.mean(periods))
    std_period = float(np.std(periods, ddof=1))
    if std_period == 0.0:
        regularity = float("inf")
    else:
        regularity = mean_period / (3.0 * std_period)
    return regularity, mean_period
