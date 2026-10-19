# exp24: confirmation of candidate I against the shipped ACF detector A (protocol frozen 2026-10-19, BEFORE any run)

**This is the last round of the ACF-variant line.** If I fails, nothing ships and no exp25 follows for ACF variants.
Rule designed with an Opus advisor after exp23 (two failed rounds). Everything is synthetic.

## Why a confirmation and not a selection

exp21 and exp23 both chose the candidate with the highest sensitivity, which was the one closest to the false-alarm
limit, and both then failed on test seeds (G on L, J on F by one cell). Here only one candidate is run, fixed before
any new data, so nothing is selected on the new seeds.

Disclosure, in full: candidate I was singled out after exp21's test result (where it was not tested) and seen again
on exp23's development seeds. Forking paths so far:

| Round | Variants tried | Seeds used | Outcome |
| --- | --- | --- | --- |
| exp20 | A-E (bands, crossings, lag range, unbiased ACF) | 0..99 dev | none met F, no test |
| exp21 design | 7 sketches incl. cumulative bands, lobe-share gates, peak gates | 5000..5029 | peak gate found |
| exp21 | A, F, G, H, I | 2000..2099 dev, 3000..3099 test | G chosen, failed L |
| exp23 | A, I, J, M | 4000..4099 dev, 6000..6099 test | J chosen, failed F |

The shipped detector A failed F on every seed set: 11 %, 9 %, 12 %, 9 % in its worst negative cell. A
clean confirmation controls selection on new data, not the design bias above.

## Candidates (fixed)

- A (shipped): `AcfConfig()` = biased ACF, constant Bartlett band, 7 crossings, lags up to n/2, no peak gate.
- I: `AcfConfig(min_crossings=5, max_lag_fraction=0.75, peak_z=3.0)`, otherwise the defaults (biased ACF,
  constant Bartlett band).

## Signals and seeds

exp20 generator `g20_signals.py`, unchanged, same 21 negative and 378 positive cells. Negative seeds 8000..8399
(400 per cell); positive seeds 8000..8099 (100 per cell). Unspent before this run (checked by search).
Report-only cells (they do NOT gate the decision; defined here by me, not by the generator's author): AR(2)
x[k] = 2 r cos(w) x[k-1] - r^2 x[k-2] + e[k] with r in {0.9, 0.97}, w = 2 pi / 20, n in {300, 1000, 3000}
(a narrow-band stochastic resonance, not a limit cycle); drift plus noise: random walk with step std 0.05 plus white
noise std 1, n in {300, 1000, 3000}. Seeds 8000..8399.

## Ship rule (frozen; all must hold)

1. **F (absolute):** in every one of the 21 negative cells, I detects at most 12 of 400 runs (the one-sided 95 %
   Clopper-Pearson upper bound of 12/400 is about 5 %), and pooled false alarms are <= 2 %. Power note: at a true
   rate of 2 % per cell the chance of a spurious fail somewhere is about 6 %; at I's earlier rate (about 1 %), passing
   is near-certain if the rate holds.
2. **S:** I's S (cells c >= 5, SNR >= 1) is at least A's S + 10 points, same seeds.
3. **L:** I's L (cells c = 20, SNR >= 1) is at least A's L - 2 points, same seeds.
4. **No cell worse than A by much:** in every negative cell I's detections <= A's detections + 2 (of 400).

If all hold: I's constants become the `AcfConfig` defaults (claim: "beats A on the synthetic suite"). In both cases
the loop report gains an honest caveat about the remaining false-alarm risk on fast noise. Reported without target:
the n = 300, c = 20 cells (period 15 samples) separately, and the report-only cells for I and A.

## RESULT (2026-10-19, `results24.md`, one run)

| | worst negative cell | pooled false alarms | S | L |
| --- | --- | --- | --- | --- |
| I | 5/400 (AR(0.5) n=3000) | 0.2 % | 78.9 % | 82.97 % (2987/3600) |
| A (shipped) | 36/400 (AR(0.5) n=3000), 29/400 white n=3000 | 1.1 % | 50.2 % | 85.03 % (3061/3600) |

F PASS, S PASS, no-cell-worse PASS, **L MISS by 2 runs of 3600** (needed >= 83.03 %). **Ship I: no.** As frozen,
the ACF-variant line ends here; A stays. Report-only: both detect the AR(2) r = 0.97 resonance in 30-42 % of runs (a
narrow-band disturbance, arguably a real cycle); drift is not detected; at n = 300, c = 20 I loses 2-6 points to A.

Consequence in the package: the ACF "oscillating" finding now says that the method reports a cycle in up to 9 % of
records of 1000+ samples of fast noise (A's rates here: 29/400 and 36/400) and asks to confirm the cycle on the trend.
