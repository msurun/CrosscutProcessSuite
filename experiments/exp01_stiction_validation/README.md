# Experiment 1: does `detect_stiction` find the stiction we inject?

`python experiments/exp01_stiction_validation/exp01.py` runs the mill-circuit scenario `stiction` (HPGR press loop)
for bands 0, 2, 4, 8 % x two noise levels x 5 seeds, with one setpoint step at 30 min (a loop sitting exactly at its
setpoint never leaves the valve deadband, so it never hunts). The detector sees the data from 2 h on. Table: `results/summary.md`.

Findings (2026-10-13): with low noise and a band of 4 % or more the detector says "stiction" in 5 of 5 runs; a healthy valve
is never flagged (it answers "inconclusive"); a band of 2 % is not found, and with full simulator noise the detector abstains
in every run (the noisy limit cycle is not periodic enough). Earlier "always inconclusive" results came from a loop with
no persistent offset. Not validated on real plant data.
