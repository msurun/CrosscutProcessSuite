# exp20: ACF oscillation detector on short records (protocol frozen 2026-10-18, BEFORE any run)

Question: which variant of the parameter-free ACF detector (`crosscut_loops.oscillation_acf`) detects limit cycles
in records with only 3-10 cycles without raising false alarms on non-oscillating disturbances? exp19 showed that the
shipped variant needs about 10 cycles in the record (ISDB records are short). Everything here is synthetic;
SACAC and ISDB are not used (seen twice). A winner supports "works on the synthetic suite", nothing about plants.

## Signals (generator written by a different model from `G20_SPEC.md`, not by the author of the detector)

Each case is an error signal e[k] (PV - SP), k = 0..n-1, dt = 1 s.

Positive cells (an oscillation is present): waveform in {sine, square, lagged square} (lagged square = square wave
through a first-order lag with time constant P/8, a stiction-like PV), cycles in record c in {3, 4, 5, 6, 8, 10, 20},
n in {300, 1000, 3000}, period P = n / c (cells with P < 10 samples are skipped), period jitter: the phase advances
by 2*pi/P * (1 + 0.05 * w[k]) with w a slowly varying (AR(1) phi = 0.99, unit variance) sequence, random start phase,
amplitude 1, additive noise of two kinds {white, AR(1) phi = 0.9} with standard deviation chosen so that
amplitude / noise std = SNR in {2, 1, 0.5}.

Negative cells (no oscillation): white noise; AR(1) with phi in {0.5, 0.9, 0.97, 0.99}; random walk; setpoint-step
response (piecewise constant level changing at Poisson times with mean spacing n/5, each level passed through a
first-order lag with time constant 20 samples, plus white noise std 0.2 of the step size); n in {300, 1000, 3000}.

Seeds: development seeds 0..99 per cell; test seeds 1000..1099 per cell, used once, after the choice.

## Candidates (defined now; no candidate may be added after the development run)

All share the Thornhill regularity r = mean(Tp) / (3 std(Tp)) > 1 and the hysteresis crossing rule.

| Id | Noise band | Min crossings | Max lag | ACF scaling |
| --- | --- | --- | --- | --- |
| A (shipped) | Bartlett, q = first zero crossing | 7 | n/2 | biased |
| B | white, 1.96/sqrt(n) | 5 | n/2 | biased |
| C | Bartlett, q = first zero crossing | 5 | 3n/4 | biased |
| D | Bartlett, q = first zero crossing | 5 | 3n/4 | unbiased (divide by n - k) |
| E | Bartlett, q = first zero crossing | 5 | n/2 | biased |

## Targets (frozen)

- **F (false alarms), hard:** detected share <= 5 % in EVERY negative cell, and <= 2 % pooled over all negative cells.
- **S (sensitivity):** pooled detection over positive cells with c >= 5 and SNR >= 1 is >= 90 %; reported separately
  for c in {3, 4} and SNR = 0.5 (no target there).
- **L (no regression on long records):** detection in cells with c = 20 and SNR >= 1 is >= 98 %.
- **Selection on development seeds:** among candidates meeting F, the one with the highest S pool; ties go to the
  earlier letter. If none meets F, nothing ships and the result is reported as it is.
- **Confirmation on test seeds, once:** the chosen candidate must meet F, S and L on the test seeds; otherwise the
  shipped detector stays and the miss is reported. Constants are not edited after the development run.
- Reported, no target: per-cell detection and false-alarm shares; reason counts ("too few ACF zero crossings",
  "irregular") per candidate, which inform a later "inconclusive: too few cycles" note in the loop report.

## RESULT, development run (2026-10-18, commit 3cf094e, dev seeds 0..99; `results20_dev.md`)

| Candidate | F (every cell <= 5 %, pool <= 2 %) | worst negative cell | pooled false alarms | S pool | L | c 3-4 | SNR 0.5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A (shipped) | no | AR(1) 0.5, n=3000: 11 % | 0.9 % | 50.9 % | 86.2 % | 0.0 % | 18.1 % |
| B | no | AR(1) 0.9, n=1000: 30 % | 9.7 % | 95.6 % | 92.9 % | 0.3 % | 46.5 % |
| C | no | AR(1) 0.5, n=1000: 14 % | 2.2 % | 83.4 % | 86.2 % | 1.5 % | 35.3 % |
| D | no | AR(1) 0.9, n=1000: 22 % | 6.0 % | 91.1 % | 86.0 % | 52.9 % | 52.6 % |
| E | no | AR(1) 0.5, n=1000: 14 % | 2.3 % | 81.8 % | 87.9 % | 0.0 % | 32.6 % |

**No candidate meets F, so per the protocol nothing ships and the test phase is not run.** The shipped detector stays.

Findings that change what may be claimed about the SHIPPED detector (A):
- It raises false alarms on fast-decorrelating noise: AR(1) phi 0.5 at 11 % (n = 3000) and 4 % (n = 1000), white
  noise 3 % at n = 1000. The earlier synthetic checks (2026-10-18) did not include AR(1) 0.5. An "oscillating"
  finding from the ACF method is therefore not reliable on its own when the error is fast noise.
- It detects 51 % of the positive cells with >= 5 cycles and SNR >= 1, and 0 % with 3-4 cycles; even with 20
  cycles only 86 % (the 5 % period jitter and AR noise were absent from the earlier checks).
- Every candidate that gains sensitivity (B, D) does so by more false alarms; C and E sit between.

Diagnostic read (not a new candidate), checked after the run on dev seeds: the shipped detector's false alarms have
LONG periods (67-337 samples on AR(0.5) and white noise, n = 1000-3000), not a few samples. For fast noise the
Bartlett band shrinks to about 1.96/sqrt(n), while the ACF estimation error at distant lags is correlated from lag
to lag and forms slow waves that leave that band. A minimum period would not remove them; a band that grows with
the lag (Bartlett summed up to each lag k) or a significance test of the whole ACF shape would be the candidates to
try. A next round needs its own frozen protocol, new seeds (0..99 are spent for selection) and candidates defined
before its run.