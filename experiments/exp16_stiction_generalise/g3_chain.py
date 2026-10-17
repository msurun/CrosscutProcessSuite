"""
g3_chain.py - Measurement chain for G3 simulated records.

Applies sensor noise, lowpass filtering, quantisation, optional historian
compression, optional missing-data gaps, and a random DC offset to clean
PV and OP signals (in percent of range, 0-100). The chain is deterministic
given the provided `np.random.Generator`.

All parameters (noise colour, filter time constant, quantisation step,
whether compression/gaps are applied, gap positions and lengths, offset)
are drawn inside this module and returned only through the processed arrays;
no metadata is returned.
"""

from dataclasses import dataclass

import numpy as np

# Measurement chain probabilities and bounds (from G3 spec)
HISTORIAN_COMPRESSION_PROBABILITY = 0.30
MISSING_DATA_PROBABILITY = 0.10
NOISE_STD_FRACTION = {"low": 0.002, "mid": 0.01, "high": 0.04}
AR1_COEFFICIENT_MAX = 0.8
SENSOR_FILTER_TC_MAX_SAMPLES = 3.0
QUANTISATION_STEP_MIN_PERCENT = 0.05
QUANTISATION_STEP_MAX_PERCENT = 0.5
COMPRESSION_DEADBAND_MIN_PERCENT = 0.1
COMPRESSION_DEADBAND_MAX_PERCENT = 0.5
GAP_COUNT_MIN = 1
GAP_COUNT_MAX = 3
GAP_LENGTH_MIN_SAMPLES = 3
GAP_LENGTH_MAX_SAMPLES = 30
OFFSET_RANGE_PERCENT = 5.0


@dataclass
class _MeasurementChainParameters:
    """Internal container for all randomly drawn chain settings."""

    noise_std_percent: float
    noise_is_ar1: bool
    ar1_coefficient: float
    sensor_filter_tc_samples: float
    quantisation_step_percent: float
    apply_historian_compression: bool
    historian_deadband_percent: float
    apply_missing_data: bool
    gap_starts: np.ndarray
    gap_lengths: np.ndarray
    offset_percent: float


def _draw_chain_parameters(
    rng: np.random.Generator, noise: str, swing: float
) -> _MeasurementChainParameters:
    """Randomly draw every parameter of the measurement chain.

    Args:
        rng: Random generator for reproducible draws.
        noise: Noise level key ("low", "mid", "high").
        swing: PV swing in percent, used to scale the noise standard deviation.

    Returns:
        A dataclass with all chain settings.
    """
    noise_std_percent = NOISE_STD_FRACTION[noise] * swing
    noise_is_ar1 = bool(rng.random() < 0.5)
    ar1_coefficient = float(rng.uniform(0.0, AR1_COEFFICIENT_MAX))
    sensor_filter_tc_samples = float(rng.uniform(0.0, SENSOR_FILTER_TC_MAX_SAMPLES))
    quantisation_step_percent = float(
        rng.uniform(QUANTISATION_STEP_MIN_PERCENT, QUANTISATION_STEP_MAX_PERCENT)
    )
    apply_historian_compression = bool(rng.random() < HISTORIAN_COMPRESSION_PROBABILITY)
    historian_deadband_percent = float(
        rng.uniform(COMPRESSION_DEADBAND_MIN_PERCENT, COMPRESSION_DEADBAND_MAX_PERCENT)
    )
    apply_missing_data = bool(rng.random() < MISSING_DATA_PROBABILITY)
    gap_count = int(rng.integers(GAP_COUNT_MIN, GAP_COUNT_MAX + 1))
    gap_starts = np.sort(rng.integers(0, 2000, size=gap_count))  # placeholder, will be rescaled
    gap_lengths = rng.integers(GAP_LENGTH_MIN_SAMPLES, GAP_LENGTH_MAX_SAMPLES + 1, size=gap_count)
    offset_percent = float(rng.uniform(-OFFSET_RANGE_PERCENT, OFFSET_RANGE_PERCENT))
    return _MeasurementChainParameters(
        noise_std_percent=noise_std_percent,
        noise_is_ar1=noise_is_ar1,
        ar1_coefficient=ar1_coefficient,
        sensor_filter_tc_samples=sensor_filter_tc_samples,
        quantisation_step_percent=quantisation_step_percent,
        apply_historian_compression=apply_historian_compression,
        historian_deadband_percent=historian_deadband_percent,
        apply_missing_data=apply_missing_data,
        gap_starts=gap_starts,
        gap_lengths=gap_lengths,
        offset_percent=offset_percent,
    )


def _add_measurement_noise(
    signal: np.ndarray,
    std_percent: float,
    is_ar1: bool,
    coefficient: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Add white or AR(1) measurement noise to a signal.

    Args:
        signal: Clean signal array (percent).
        std_percent: Noise standard deviation in percent.
        is_ar1: If True, generate AR(1) noise, otherwise white noise.
        coefficient: AR(1) coefficient (between 0 and 0.8).
        rng: Random generator.

    Returns:
        Signal with additive noise.
    """
    white_noise = rng.normal(0.0, std_percent, size=signal.shape)
    if not is_ar1:
        return signal + white_noise
    ar1_noise = np.empty_like(white_noise)
    ar1_noise[0] = white_noise[0]
    for i in range(1, len(white_noise)):
        ar1_noise[i] = coefficient * ar1_noise[i - 1] + white_noise[i]
    return signal + ar1_noise


def _apply_sensor_lowpass(signal: np.ndarray, time_constant_samples: float) -> np.ndarray:
    """Apply a first-order lowpass filter to a signal.

    Uses the exact discrete-time equivalent of a continuous first-order
    filter with sampling interval 1 sample. The filter is applied
    forward in time (no bidirectional filtering).

    Args:
        signal: Input signal array.
        time_constant_samples: Filter time constant in samples.

    Returns:
        Filtered signal.
    """
    if time_constant_samples <= 0.0:
        return signal.copy()
    alpha = 1.0 / (time_constant_samples + 1.0)
    filtered = np.empty_like(signal)
    filtered[0] = signal[0]
    for i in range(1, len(signal)):
        filtered[i] = filtered[i - 1] + alpha * (signal[i] - filtered[i - 1])
    return filtered


def _quantise(signal: np.ndarray, step_percent: float) -> np.ndarray:
    """Quantise a signal to a uniform grid with given step size.

    Args:
        signal: Input signal array (percent).
        step_percent: Quantisation step in percent.

    Returns:
        Quantised signal.
    """
    return np.round(signal / step_percent) * step_percent


def _apply_historian_compression(signal: np.ndarray, deadband_percent: float) -> np.ndarray:
    """Apply deadband compression followed by linear interpolation to regular grid.

    The historian keeps only samples that deviate from the last recorded
    value by more than the deadband; all other samples are replaced by
    linearly interpolated values between the retained samples.

    Args:
        signal: Input signal array.
        deadband_percent: Compression deadband in percent.

    Returns:
        Signal after compression and interpolation (same length).
    """
    if len(signal) == 0:
        return signal.copy()
    kept_indices = [0]
    last_kept_value = signal[0]
    for i in range(1, len(signal)):
        if abs(signal[i] - last_kept_value) > deadband_percent:
            kept_indices.append(i)
            last_kept_value = signal[i]
    kept_indices = np.array(kept_indices)
    if len(kept_indices) == 1:
        # All samples within deadband of the first: constant signal.
        return np.full_like(signal, signal[0])
    all_indices = np.arange(len(signal))
    return np.interp(all_indices, kept_indices, signal[kept_indices])


def _apply_missing_data(
    signal: np.ndarray, gap_starts: np.ndarray, gap_lengths: np.ndarray
) -> np.ndarray:
    """Replace specified gaps in a signal with hold-last-value.

    The value immediately before each gap is repeated for the whole gap.

    Args:
        signal: Input signal array.
        gap_starts: Start indices of gaps (int array).
        gap_lengths: Lengths of gaps in samples (int array, same size).

    Returns:
        Signal with gaps filled by hold-last-value.
    """
    result = signal.copy()
    for start, length in zip(gap_starts, gap_lengths):
        start = int(start)
        length = int(length)
        if start == 0:
            # No previous value; use first available value after the gap.
            fill_value = result[min(length, len(result) - 1)]
        else:
            fill_value = result[start - 1]
        end = min(start + length, len(result))
        result[start:end] = fill_value
    return result


def apply_chain(
    rng: np.random.Generator,
    pv: np.ndarray,
    op: np.ndarray,
    noise: str,
    swing: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the full G3 measurement chain to clean PV and OP arrays.

    The chain consists of:
      1. additive measurement noise (white or AR(1)),
      2. sensor lowpass filtering,
      3. independent quantisation,
      4. optional historian deadband compression with linear interpolation,
      5. optional missing-data gaps with hold-last-value,
      6. a random DC offset (same for PV and OP? No, spec says "a random
         offset" – apply same offset to both for consistency with a
         calibration error).

    Args:
        rng: Random generator for reproducible parameter draws.
        pv: Clean PV array (percent, 0-100).
        op: Clean OP array (percent, 0-100).
        noise: "low", "mid", or "high".
        swing: PV swing in percent, used to scale noise standard deviation.

    Returns:
        Tuple (processed_pv, processed_op), same length as inputs.
    """
    if noise not in NOISE_STD_FRACTION:
        raise ValueError(f"Unknown noise level: {noise!r}")
    if pv.shape != op.shape:
        raise ValueError("PV and OP must have the same length")
    if len(pv) == 0:
        return pv.copy(), op.copy()

    params = _draw_chain_parameters(rng, noise, swing)

    # Rescale gap starts to the actual signal length.
    n_samples = len(pv)
    gap_starts = np.minimum(params.gap_starts, n_samples - 1)
    # Ensure gaps do not extend beyond the end.
    gap_lengths = np.minimum(params.gap_lengths, n_samples - gap_starts)

    # Apply noise and sensor filter to both signals.
    pv_noisy = _add_measurement_noise(
        pv, params.noise_std_percent, params.noise_is_ar1, params.ar1_coefficient, rng
    )
    op_noisy = _add_measurement_noise(
        op, params.noise_std_percent, params.noise_is_ar1, params.ar1_coefficient, rng
    )
    pv_filtered = _apply_sensor_lowpass(pv_noisy, params.sensor_filter_tc_samples)
    op_filtered = _apply_sensor_lowpass(op_noisy, params.sensor_filter_tc_samples)

    # Quantise independently.
    pv_quantised = _quantise(pv_filtered, params.quantisation_step_percent)
    op_quantised = _quantise(op_filtered, params.quantisation_step_percent)

    # Optional historian compression.
    if params.apply_historian_compression:
        pv_compressed = _apply_historian_compression(
            pv_quantised, params.historian_deadband_percent
        )
        op_compressed = _apply_historian_compression(
            op_quantised, params.historian_deadband_percent
        )
    else:
        pv_compressed = pv_quantised
        op_compressed = op_quantised

    # Optional missing data.
    if params.apply_missing_data:
        pv_gapped = _apply_missing_data(pv_compressed, gap_starts, gap_lengths)
        op_gapped = _apply_missing_data(op_compressed, gap_starts, gap_lengths)
    else:
        pv_gapped = pv_compressed
        op_gapped = op_compressed

    # Apply DC offset (same offset to both signals).
    pv_out = pv_gapped + params.offset_percent
    op_out = op_gapped + params.offset_percent

    return pv_out, op_out
