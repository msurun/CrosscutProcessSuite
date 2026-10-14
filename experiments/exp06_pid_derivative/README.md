# exp06: does derivative action (AMIGO PID) beat AMIGO PI, and when not?

Question (C3 part 2): `tuning_pid.amigo_pid` adds a derivative term. `derivative_advice` says it pays off only when the
normalized dead time L/(L+T) is at most 0.5 (our threshold, a heuristic after Astrom and Hagglund 2006, section 7.4: the benefit is
marginal for delay-dominated processes). Is that true on exact FOPDT loops?

Setup: process K = 1, T + L = 100 s, normalized dead time tau_n = L/(L+T) in {0.1, 0.2, 0.3, 0.5, 0.7, 0.9}, sampled at 0.5 s
(`crosscut_sim.core.Fopdt`). Controllers: `amigo_pi` against `amigo_pid` (ideal form, derivative filter N = 10, derivative on the
measurement). Load disturbance: unit step added at the process input; metric IAE over 15 (T + L). Robustness: peak sensitivity Ms
from the frequency response (exact delay, no Pade). Noise: PV noise sd 0.01, ratio of the std of the controller-output increments
PID / PI (informational).

## Acceptance targets (frozen before the first run, 2026-10-14)

- **P1:** for tau_n <= 0.3 the load-step IAE of the PID is at most 0.8 x the IAE of the PI (at least 20 % better) at every grid point.
- **P2:** Ms of the PID is at most 1.8 at every grid point (the AMIGO rule is meant to be conservative).
- **P3:** for tau_n >= 0.7 `derivative_advice` returns False and the PID improves the IAE by less than 10 % (ratio >= 0.9).
- **P4 (informational):** report Kc (1 + N) and the noise ratio for every grid point.

If a target is missed the finding is logged as it is; the thresholds are not changed afterwards.

## Result (run 2026-10-14, `python exp06.py`, table in `results/results.md`)

P1 PASS (worst IAE ratio 0.41 at tau_n 0.1). P2 PASS (worst Ms 1.45). **P3 FAIL**: at tau_n 0.7 the PID still improves the IAE by 30 %
(ratio 0.70), at 0.9 by 6 % (ratio 0.94). The "marginal for delay-dominated" statement of the book holds on this grid only from about
tau_n 0.85. The advice threshold 0.5 was NOT changed after seeing this (frozen rule); it is conservative, not wrong: at 0.5 the
PID has IAE ratio 0.43, which matches the book's "about a doubling of the integral gain".

Post-hoc points (run afterwards, not part of the frozen targets): IAE ratio 0.40 -> 0.55 at tau_n 0.4/0.6 -> 0.86 at 0.8; Ms of the PID stays
1.40-1.45 everywhere.

**The cost is noise** (the code review found that the first script took the std of the second difference of the output instead of the increments; fixed and re-run, the ratios moved by less than 0.3, 12.6 to 25.4 on the grid, 26.7 post hoc at tau_n 0.4).
 The std of the controller-output increments with PV noise sd 0.01 is 13-27 times larger with the PID than with the
PI (the PID's Kc(1+N) is 2.8 at tau_n 0.9 and 47 at 0.1). Derivative action therefore needs a quiet or filtered PV; the advice text now says so.
Limits: exact FOPDT process (no model error, no valve), unit load step only, noise white and small, N fixed at 10. The ratio of noise to
benefit on a real loop depends on the real noise and on actuator wear, which this does not model.
