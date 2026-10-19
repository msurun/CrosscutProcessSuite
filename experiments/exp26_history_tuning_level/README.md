# exp26: tuning from history on level (integrating) loops - is a confident recommendation safe? (frozen 2026-10-19)

`history_tuning.tune_from_history` fits a FOPDT model to natural setpoint steps and grades it high / medium / low /
none. It was validated on self-regulating loops only (exp17). A level loop is an integrator: a FOPDT fit on a short
window can return a moderate time constant, SIMC then sets Ti = tau, and an integrating process with a short Ti
oscillates. Question: when the tool says "retune" (high) or "retune_cautiously" (medium) on a level loop, is the
recommended PI safe on that loop? Everything is synthetic; nothing about plants.

## Simulated loops (generator G26, written by a different model than the harness author)

`g26_level.simulate_history(case, seed) -> dict(t_s, sp, op, pv)` and `g26_level.step_response(case, kc, ti_s,
seed) -> dict(t_s, sp, pv, op)`; dt = 1 s.
- Plant: pure integrator with dead time, dPV/dt = k (u(t - theta) + d(t)), k in {0.01, 0.05} %PV per %OP per
  second, theta in {2, 10} s; u = OP - 50 (OP limits 0..100), PV starts at 50.
- Running controller (history): ISA PI (`crosscut_sim.pid.PID`), SIMC for integrating processes with
  tau_c = theta x m: Kc = 1 / (k (tau_c + theta)), Ti = 4 (tau_c + theta), m in {1 ("good"), 3 ("sluggish")}.
  Direct/reverse action so that the loop is stable (k > 0: reverse acting).
- History: n = 8000 samples; setpoint steps at Poisson times with mean spacing 1500 s, size uniform in +-[2, 8] %
  PV around 50 (kept within 30..70); load d = Ornstein-Uhlenbeck, std in {0, 1} % OP, time constant 200 s;
  measurement noise std in {0, 0.2} % PV.
- `step_response`: the same plant with the given PI from rest at SP = PV = 50, a +5 % SP step at t = 50 s, run for
  T = 50 + 40 (theta + 4 / (k Kc)) s rounded up, plus the case's load and noise.
- Cells: 2 k x 2 theta x 2 tunings x 2 load x 2 noise = 32; seeds 0..24 per cell, one run.

## Procedure

For each run: `tune_from_history("L", sp, op, pv, dt_s=1)`; if confidence is high or medium, take
`report.simc` (Kc, Ti), simulate `step_response` with it and with the running controller. Safety of a recommended
tuning: the closed loop is **settled** when max |PV - SP| over the last 25 % of the response is <= 10 % of the step
and **not oscillating** when the error changes sign at most 4 times after the first crossing of the new setpoint
(by more than 2 % of the step on each side).

## Targets (frozen)

- **H1 (safety):** every high or medium recommendation is settled and not oscillating (100 %; a single unsafe
  case fails H1). Reported with the count of high/medium runs; if there are none, H1 is "not exercised".
- Reported, no target: confidence shares per cell; identified gain / tau vs the true integrator (k ~ K / tau for
  a FOPDT fit); recommended Kc and Ti vs the integrating SIMC rule above with tau_c = theta; the running
  controller's own settled share as a reference.
- If H1 fails: `tune_from_history` gains a guard (refuse high/medium when the fitted tau exceeds a multiple of the
  window length or the fit looks integrating), designed in a new frozen round; until then the README and the
  tuning report say that level loops are not validated.
