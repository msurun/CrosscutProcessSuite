# exp08: cascade tuning order and time-scale separation

Question (C3 part 2): `cascade.plan_cascade` tunes the inner loop first (SIMC, tau_c2 = effective delay), identifies the outer
model with the inner loop closed, and sets tau_c1 = max(sigma tau_c2, outer delay). Skogestad's lecture (APC6, NTNU) states the
rule sigma = tau_c1 / tau_c2 = 4 to 10 (4 after Shinskey 1981; 10 recommended). Does the plan work, and what happens at sigma = 1?

Setup: inner process G2 = 1 / (5 s + 1) with delay 2 s; outer process G1 = 2 e^(-5 s) / (60 s + 1) driven by the inner output;
dt = 0.5 s, 5 seeds (PV noise sd 0.01 on both measurements). The outer model is identified from a setpoint step of the inner
loop (inner closed). Disturbance d2: unit step at the inner process input. Outer setpoint step +1.

## Acceptance targets (frozen before the first run, 2026-10-14)

- **C1:** with sigma = 10 and sigma = 4 the outer setpoint response overshoots at most 20 % (60 s moving average) and is settled
  (tail error below 5 % of the step) in all 5 seeds.
- **C2:** with sigma = 10 the IAE for the d2 step is at most 0.5 x the IAE of a single outer SIMC PI loop (tau_c = outer delay, no inner loop).
- **C3 (informational):** report overshoot and IAE for sigma = 1, 2, 4, 10 so the effect of too little separation is visible.

If a target is missed the finding is logged as it is; the thresholds are not changed afterwards.

## Result (run 2026-10-14, `python exp08.py`, table in `results/results.md`)

C1 MET (sigma 4 and 10: overshoot 3.3 % and 1.1 %, settled in 5 of 5 seeds). C2 MET (disturbance IAE 4.4 with the cascade at sigma 10 against
35.3 for the single outer loop, a factor 8). C3 (informational): sigma 1 / 2 / 4 / 10 give overshoot 12.1 / 9.1 / 3.3 / 1.1 % and
disturbance IAE 6.5 / 5.2 / 4.5 / 4.4. So too little separation is visible but mild on this plant: the claim of interaction and
instability for sigma < 4 was NOT reproduced; what we see is more overshoot and a slower disturbance rejection, which supports the rule
without making it a hard limit. `plan_cascade` chose tau_c_inner 1.5 s, tau_c_outer 15 s (sigma 10) with no warning.

Two things found on the way, both worth keeping:
1. **A lone step is a poor identification signal.** With the inner loop closed, `identify_fopdt` on a single +1 step returned gain 0.55,
   time constant 33 s and delay 59.5 s (true: 2, about 62, about 8). The input and the constant of the ARX regression are nearly
   collinear after the step. The experiment therefore identifies from a +1 pulse (600 s up, then down), after which gain 1.97, tau 53-56 s,
   delay 6.5-8 s. This is a change of the TEST SIGNAL after a first look; the targets were not touched. The same weakness can hit the
   tuning report when a test window holds one step only: the fit-quality guard (R squared) did not catch it here, to be checked in the code review.
2. A first version of the helper identified the inner loop's output y2 instead of y1 (the outer process was missing in the simulation);
   the first run therefore showed unstable loops at every sigma. Fixed, results above are from the corrected run.

Limits: two linear first-order plants, no valve limits or noise on the setpoint, five seeds, outer delay (5 s) larger than the inner (2 s) so the
default separation is easy to reach; a plant with a slow inner loop would stress the rule more.
