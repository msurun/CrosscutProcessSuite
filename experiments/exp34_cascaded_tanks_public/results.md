# exp34 results (run 2026-11-18, Cascaded Tanks, CC BY-SA 4.0 data, aggregate numbers only)

Run once with `run_exp34.py --data <scratch folder>`, protocol unchanged since the frozen commit. Est = estimation set, Val = validation set (1024 samples, 4 s).

| id | result | verdict |
|----|--------|---------|
| K1 | `identify_ipdt` whole record: blocked on both sets (r2 0.235 / 0.346; reasons r2_below_0.8, theta_on_grid_edge, slope_se_over_20pct, plus the multisine having no pre-move lead or settled tail) | met |
| K2 | FOPDT BIC beats IPDT BIC on whole record: Est -1156 vs 1336, Val -57 vs 1111 (FOPDT r2 0.93 / 0.79, tau 221 / 137 s, theta 32 / 48 s, gain 4.9 / 3.2) | met |
| K3 | `saturation_fraction(y, 0, 10)`: 0.048 (Est), 0.041 (Val) | met |
| K4 | `fit_step` FOPDT ran, gain > 0 on both sets | met |

All four targets met. Caveat: K1 is met mostly because the record is a multisine with no pre-move lead and no settled tail, so the lead/tail refusals fire regardless of the physics; the test does not show that a real integrating-vs-self-regulating discrimination would work on a proper step test.

## Report-only observations (not targets)
- Clip-free segment (first 150 / 151 samples, before the first sample at 10 V): `identify_ipdt` still blocked (no lead, tail too short). `fit_step` IPDT reaches r2 0.915 / 0.921; on Val its BIC (-306) beats FOPDT (-224, tau 600 s on the grid edge, flag `tau_at_edge`). A short window of a self-regulating plant looks integrating to `fit_step`.
- Tuning helpers called by the script on the blocked whole-record IPDT slope give PI Kc 0.08 / 0.056, Ti 8160 s: the helpers do not look at the verdict. The shipped payload is what refuses; the script call is only a demonstration of what would be offered if the verdict were ignored.
- Dead time of the FOPDT fit (32 to 48 s) is far above the 4 s sampling: the sampling-resolution flags did not fire there (only `theta_below_resolution` on the poor IPDT fit).

## Findings (generic engine gaps)
1. `fit_step` has no overflow / clipped-PV flag: PV samples stuck at the sensor limit (about 4 to 5 % here) go into the fit silently, while `saturation_fraction` only looks at OUT in the monitor. A PV-at-limit edge flag (and refusal above a share) would fit the existing `edges` mechanism.
2. `fit_step` "ipdt" has no discrimination against self-regulating behaviour: on a short window with r2 0.92 it wins on BIC over a FOPDT whose tau hit the grid edge. Callers must use the `identify_ipdt` verdict or the model choice rule, not r2/BIC from `fit_step` alone.
3. Not tested: step-event detection, the averaging-level recommendation on a real step, and the shipped payload path (the record has no steps). A proper open-loop step dataset is still missing.

Nothing shipped or changed in `loops/`.
