# exp25: guided valve stroke test - plan, analysis and a simulated validation (protocol frozen 2026-10-19)

Why: passive stiction detection is closed (HANDOFF, exp15/16). The decisive check is an on-plant test: the operator
puts the loop in MANUAL and moves the output in small steps up and down; the valve's deadband and resolution are read
from the PV response. This experiment builds the plan, the analysis, and checks the analysis on a simulator written by
a different model. Nothing writes to a DCS: the plan is a procedure the operator executes. Claim nothing for plants
until one real test record exists.

Definitions (wording after ANSI/ISA-75.25.01 and ISA-TR75.25.02 as recalled; the standards were NOT read):
- **Deadband (reversal):** the output travel after a direction reversal before the valve visibly moves.
- **Resolution:** the smallest same-direction output step that visibly moves the valve.
PV is used as the proxy for valve position (no positioner feedback assumed), so a visible move is a settled PV
change beyond noise, converted to output units with the process gain.

## Module spec `crosscut_loops/valve_test.py`

Plan:
- `StrokePlan(op_start, step_sizes, steps_per_leg, dwell_s, op_low, op_high, pv_band)`; frozen dataclass.
- `plan_stroke_test(op_start, dwell_s, op_low=0, op_high=100, pv_band=None, step_sizes=(1.0, 0.25),
  steps_per_leg=(4, 12)) -> list[TestStep]`: for each step size s with its leg length m, the legs are up m steps,
  down m steps, up m steps (two reversals per size), starting from the OP reached by the previous size. Each
  `TestStep(index, op_target, direction (+1/-1), size, dwell_s, after_reversal (bool: first step of a leg after the
  first leg))`. ValueError if any target leaves [op_low, op_high]. dwell_s should be at least 4 (tau + theta) of the
  loop; the analysis uses only the last third of each dwell.
- `procedure_text(plan) -> list[str]`: numbered operator instructions (switch to MANUAL at op_start, wait one dwell,
  then each step with its target and wait time, abort and return to op_start if PV leaves pv_band or anything looks
  wrong, switch back to AUTO at the end). Plain English, no vendor specifics.

Analysis `analyze_stroke_test(t_s, op, pv, plan) -> StrokeResult`:
1. Segment the record by the OP changes actually made: change points where |op[k] - op[k-1]| > 0.4 * smallest step
   size (the operator's timing may differ from the plan). Segment j runs from change point j to the next. Steady PV
   per segment = median of its last third; steady OP = median of its last third.
2. Noise: sigma_pv = 1.4826 * median absolute deviation of pv within all last thirds (deviation from each segment's
   median).
3. Gain: K = median of dPV/dOP over steps of the LARGEST size that are not the first move after a reversal and whose
   |dPV| > 3 sqrt(2) sigma_pv. None if fewer than 2 such steps: then result reason "no gain: valve did not move".
4. Visible move at segment j: |dPV_j| > max(3 sqrt(2) sigma_pv, 0.5 * |K| * smallest step).
   Valve move in output units: dV_j = dPV_j / K.
5. Deadband per reversal: cumulative |dOP| from the reversal until and including the first visibly moving step in
   the new direction = T; bracket [T - s, T] with s that step's size; estimate T - s / 2. Per step size, the median
   over its reversals. Final deadband = estimate of the smallest step size that has at least one bracketed reversal
   (fall back to larger sizes). No visible move within a leg: deadband "> leg travel" (lower bound only).
6. Resolution: for each step size, over steps that are not first-after-reversal and come after the valve already
   moved in that leg: share that moved visibly. Resolution "<= s" for the smallest s with share >= 0.75; else
   "> smallest s".
7. Abort check: `pv_left_band` True if pv_band given and any |pv - pv at start| > pv_band.
`StrokeResult(deadband, deadband_bracket, resolution_le, gain, sigma_pv, moves (list per segment), pv_left_band,
reason)`; all values in % of output span; reason "" when complete.

## Simulator spec G25 (written by a different model than the analyzer)

`g25_valve.simulate_test(case, seed) -> dict(t_s, op, pv, true_deadband, true_resolution)`. The OP follows a plan
from `plan_stroke_test` exactly (dt = 1 s, each step held for its dwell). Valve: a stick-slip model defined from the
definitions above, NOT copied from `crosscut_sim/valve.py`: the valve position v follows the command c; after a
reversal the valve holds until c has travelled `deadband` from the reversal point, then follows with a lag; in the
same direction the valve moves only in increments: it holds until c - v exceeds `resolution`, then jumps to c minus
a lag. Ground truth: true_deadband and true_resolution are the definitions above. Process: FOPDT with gain K in
{0.8, 2.0, -1.5}, tau in {3, 20} s, theta 1 s (flow-like and slower), dwell = 6 (tau + theta) rounded up to 10 s.
Measurement noise std in {0, 0.05, 0.2} % of the PV response to a 1 % step (i.e. times |K|). Load disturbance: none,
or a step of 0.3 % in output units at a random time during the test. Valve: deadband in {0, 0.3, 0.8, 2.0} %,
resolution in {0, 0.1, 0.4} % of span (all combinations with resolution <= deadband or deadband = 0).

## Targets (frozen)

- **V1 deadband:** |estimate - true| <= 0.25 % of span in >= 90 % of runs without load disturbance, pooled over
  noise levels 0 and 0.05; reported for noise 0.2 and with load disturbance (no target).
- **V2 healthy valve:** with deadband = 0 and resolution = 0, estimate <= 0.25 % in >= 95 % of runs (noise <= 0.05).
- **V3 abort:** in a suite where the load disturbance is large (5 % output units) and pv_band is set to half of the
  resulting PV deviation, `pv_left_band` is True in 100 % of runs.
- Seeds: 0..19 per cell, one run; constants not edited after the run. If V1 or V2 miss, the module ships as
  "procedure plus raw brackets" without a deadband number in the report, and the miss is documented.

## RESULT (2026-10-19, one run, `results25.md`)

V1 PASS (deadband within 0.25 % of span in 100 % of runs without load disturbance, noise 0 and 0.05), V2 PASS
(healthy valve <= 0.25 % in 100 %), V3 PASS (abort flag in 100 % of the big-disturbance suite).

Report-only: with a 0.3 % load step during the test the share within tolerance drops to 88-91 %; at noise 0.2 it is
89 %; the 0.25 % steps get lost in noise 0.2, so a healthy valve is then bracketed only by the 1 % steps (estimate
0.5 %). The resolution number was only checked for availability, not against the truth: it is reported as an upper
bound ("<= s") and not claimed.

What this supports: on a simulated FOPDT process with an instantaneous valve and a dwell of 6 (tau + theta), the
bracket estimator recovers deadbands of 0.3-2 % to within one fine step. What it does not: real valves with
positioner dynamics, PV as a poor proxy for position (slow or integrating loops, interacting loops), operators who
cannot hold the dwell. No real test record exists yet; the result in the product is labelled accordingly.
