# G20 signal generator specification (for a model that has not seen the detector)

Write `g20_signals.py` (numpy only). Public API:

```python
POSITIVE_WAVEFORMS = ("sine", "square", "lagged_square")
NOISE_KINDS = ("white", "ar09")
NEGATIVE_KINDS = ("white", "ar050", "ar090", "ar097", "ar099", "random_walk", "sp_steps")

def positive_case(waveform: str, n: int, cycles: int, snr: float, noise: str, seed: int) -> np.ndarray
def negative_case(kind: str, n: int, seed: int) -> np.ndarray
```

Both return a float array of length n, the control error with sample time 1 s. Use
`np.random.default_rng(seed)` once per call and draw everything from it, so a (cell, seed) pair is reproducible.

## positive_case

- Period P = n / cycles samples (float).
- Jitter sequence w: AR(1) with phi = 0.99 driven by standard normal innovations, then scaled to unit sample
  standard deviation (if its std is 0, use zeros).
- Phase: phi[0] uniform in [0, 2 pi); phi[k] = phi[k-1] + (2 pi / P) * (1 + 0.05 * w[k]).
- Waveform from the phase: sine = sin(phi); square = sign(sin(phi)) with sign(0) taken as +1;
  lagged_square = the square wave filtered by a first-order lag y[k] = a*y[k-1] + (1-a)*x[k],
  a = exp(-1/tau), tau = P/8 samples, y[0] = x[0], then rescaled so its peak absolute value is 1.
- Noise: "white" = standard normal; "ar09" = AR(1) with phi 0.9, standard normal innovations, x[0] drawn from the
  stationary distribution (std 1/sqrt(1 - 0.81)). Scale the noise sequence to sample std exactly 1/snr, then add.
- Raise ValueError when P < 10, cycles < 1, n < 50, snr <= 0, or a name is unknown.

## negative_case

- "white": standard normal.
- "ar050", "ar090", "ar097", "ar099": AR(1) with phi 0.5, 0.9, 0.97, 0.99, standard normal innovations, x[0] from the
  stationary distribution.
- "random_walk": cumulative sum of standard normal steps.
- "sp_steps": step times from a Poisson process with mean spacing n/5 samples (exponential gaps), at least one step;
  each step draws a new level uniform in [-1, 1]; the piecewise-constant level sequence passes through a first-order
  lag with tau = 20 samples (same filter form as above, y[0] = level[0]); add white noise with std 0.2.
- Raise ValueError for an unknown kind or n < 50.

## Rules

Functions <= 20 lines, <= 4 parameters, docstrings everywhere, type hints, no prints, no plotting, line length <= 100.
