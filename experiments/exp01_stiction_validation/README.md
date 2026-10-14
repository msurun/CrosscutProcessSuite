# Experiment 1: does `detect_stiction` find the stiction we inject?

`python experiments/exp01_stiction_validation/exp01.py` runs the mill-circuit scenario `stiction` (HPGR press loop)
for bands 0, 2, 4, 8 % x two noise levels x 5 seeds, with one setpoint step at 30 min (a loop sitting exactly at its
setpoint never leaves the valve deadband, so it never hunts). The detector sees the data from 2 h on. Table: `results/summary.md`.

Findings (2026-10-13): with low noise and a band of 4 % or more the detector says "stiction" in 5 of 5 runs; a healthy valve
is never flagged (it answers "inconclusive"); a band of 2 % is not found, and with full simulator noise the detector abstains
in every run (the noisy limit cycle is not periodic enough). Earlier "always inconclusive" results came from a loop with
no persistent offset. Not validated on real plant data.

## Acceptance run for the OUT-shape detector (criteria frozen 2026-10-13, before the run)

Method: `detect_stiction` now judges the shape of OUT (stiction index, thresholds 0.6 and 0.4 from the paper, not tuned).
Run: `python experiments/exp01_stiction_validation/acceptance.py` (20 seeds per class, seeds 1-10 development, 11-20 held out;
the thresholds are not to be touched after looking at the held-out seeds).

- Positives (valve band 2, 4, 6, 8 %, one setpoint step): report the detection rate per band and noise level.
  Target: band >= 6 % found in >= 80 % of the held-out seeds at both noise levels; band 4 % at low noise likewise.
  Bands that miss the target are reported as they are, with the verdicts they got instead.
- Negatives (healthy valve), reported per class, never pooled: nominal wander with a step, aggressive tuning (Kc x3, Ti/3),
  sinusoidal setpoint forcing (period 1200 s), square-wave setpoint forcing (adversarial, failures expected).
  Target: no "stiction" verdict for the first three classes in the held-out seeds; the 95 % upper bound of the false-alarm
  rate is stated (0 of 10 still allows up to 26 %, 0 of 20 up to 14 %). The square wave is documented as a known limit.
- Out of scope: integrating processes, real plant data.

### Result of the acceptance run (2026-10-13, report: `results/acceptance.md`)

Held-out seeds 11-20, 10 per cell:

| Case | Verdict "stiction" |
|---|---|
| band 4, 6, 8 %, low noise | 10 of 10 each |
| band 8 %, full noise | 8 of 10 |
| band 6 %, full noise | 2 of 10 (rest inconclusive) |
| band 2 % (both noise levels), band 4 % full noise | 0 of 10 (all inconclusive) |
| healthy: nominal wander, aggressive tuning, sine forcing | 0 of 10 each (95 % upper bound 27.8 %); sine forcing is classed "no_stiction" |
| healthy: square-wave setpoint forcing | 10 of 10 false alarms |

Against the frozen targets: met at low noise; at full noise only band 8 % is met, bands 6 % and below abstain instead of guessing.
The square wave is a known limit of the method (a periodic square disturbance also gives a triangular OUT): do not trust a
"stiction" verdict on a loop with a periodic external forcing. Nothing was tuned on the held-out seeds. The PV-only method it
replaces never produced a verdict under full noise. Only 10 seeds per cell: the false-alarm bound is wide.
