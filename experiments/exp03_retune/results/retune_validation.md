# Retune Validation Experiment (exp03)

## Acceptance Targets
- **Loop improvement**: `IAE_after_simc <= 0.8 * IAE_before` and `not unstable`.
- **Seed pass**: at least 2 of 3 loops improve under SIMC.
- **Experiment pass**: at least 4 of 5 seeds pass.

## Results Table
| Seed | Loop | Blocked | SIMC Kc | SIMC Ti (s) | IAE Before | IAE SIMC | IAE AMIGO | Imp % | Overshoot | Settling (s) | Health Before | Health SIMC | Unstable | Improved |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | cyc_water | False | 2.931 | 16.0 | 22929.1 | 4691.6 | 4613.7 | 79.5% | 34.8% | 12599 | 61.0 | 100.0 | False | True |
| 1 | hpgr_press | False | 32.662 | 32.8 | 2704.7 | 298.3 | 278.1 | 89.0% | 10.8% | 12586 | 45.0 | 99.0 | False | True |
| 1 | mill_feed | False | 1.655 | 16.0 | 26530.2 | 7790.5 | 7539.7 | 70.6% | 66.8% | 12599 | 72.0 | 100.0 | False | True |
| 2 | cyc_water | False | 2.312 | 16.0 | 22883.9 | 4888.5 | 4717.7 | 78.6% | 37.3% | 12597 | 62.0 | 100.0 | False | True |
| 2 | hpgr_press | False | 106.102 | 16.0 | 2666.8 | 191.5 | 180.6 | 92.8% | 6.7% | 12528 | 45.0 | 100.0 | False | True |
| 2 | mill_feed | False | 1.678 | 16.0 | 27684.1 | 7812.9 | 7547.2 | 71.8% | 57.9% | 12599 | 68.0 | 100.0 | False | True |
| 3 | cyc_water | False | 3.332 | 16.0 | 23798.2 | 4569.1 | 4551.2 | 80.8% | 33.1% | 12597 | 62.0 | 100.0 | False | True |
| 3 | hpgr_press | False | 109.196 | 16.0 | 2662.5 | 187.4 | 178.0 | 93.0% | 6.9% | 12509 | 45.0 | 100.0 | False | True |
| 3 | mill_feed | False | 1.337 | 16.0 | 30092.8 | 8190.8 | 7822.1 | 72.8% | 60.2% | 12599 | 69.0 | 100.0 | False | True |
| 4 | cyc_water | False | 3.272 | 16.0 | 23190.8 | 4614.4 | 4565.7 | 80.1% | 34.0% | 12598 | 63.0 | 100.0 | False | True |
| 4 | hpgr_press | False | 133.230 | 16.0 | 2552.8 | 185.8 | 178.0 | 92.7% | 7.1% | 11978 | 46.0 | 100.0 | False | True |
| 4 | mill_feed | False | 1.557 | 16.0 | 27976.1 | 7975.0 | 7722.2 | 71.5% | 61.7% | 12599 | 70.0 | 100.0 | False | True |
| 5 | cyc_water | True | - | - | - | - | - | - | - | - | - | - | False |
| 5 | hpgr_press | False | 90.609 | 16.0 | 2612.8 | 197.1 | 186.4 | 92.5% | 8.1% | 12525 | 45.0 | 100.0 | False | True |
| 5 | mill_feed | False | 1.855 | 16.0 | 30755.1 | 7641.6 | 7452.0 | 75.2% | 63.4% | 12598 | 65.0 | 100.0 | False | True |

## Summary
- **Seeds passing (>= 2 improved loops)**: 5 / 5
- **Overall Verdict**: **PASS**

## Limits
Result: PASS on the frozen targets (5 of 5 seeds). 14 of 15 loop runs improved, IAE 70-93 % lower than the detuned loop. The 15th run (seed 5, cyc_water) was blocked by the poor-fit guard (P6.4): R squared -1.18 on a noisy step window, consistent with exp02 where the cyc_water time constant error reaches 487 % at the 90th percentile; the guard did what it is for, an engineer would pick another window. Caveats. (1) Settling time is almost the whole window in nearly every run: the 5 % band is below the measurement and process noise, so that column carries no information. (2) Overshoot is high for mill_feed (58-67 %) and cyc_water (33-37 %) for SIMC at robustness 0.5; probably loop interaction (the other two loops stay detuned) and the model error of exp02; not investigated. (3) Health 100 after retuning is the ceiling of the score, not extra proof. (4) IAE before is dominated by a sluggish loop that does not reach the new setpoint inside the window. (5) Only setpoint steps, operator off, one plant model; no load disturbances. AMIGO gives almost the same numbers as SIMC. (6) Tuning stays advisory: nothing is written to a DCS.
