# exp08: cascade tuning order and time-scale separation

Seeds run: 5, valid: 5, failed: 0.

## Per-seed results

| seed | sigma | overshoot % | settled | IAE setpoint | IAE disturbance |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 10.69 | True | 24.761 | 5.220 |
| 1 | 2 | 7.75 | True | 21.549 | 4.693 |
| 1 | 4 | 2.81 | True | 19.477 | 4.269 |
| 1 | 10 | 1.31 | True | 26.161 | 4.297 |
| 2 | 1 | 14.90 | True | 38.800 | 7.556 |
| 2 | 2 | 11.24 | True | 26.271 | 5.525 |
| 2 | 4 | 5.45 | True | 20.320 | 4.517 |
| 2 | 10 | 0.85 | True | 23.716 | 4.300 |
| 3 | 1 | 11.70 | True | 27.060 | 5.776 |
| 3 | 2 | 8.69 | True | 22.491 | 5.080 |
| 3 | 4 | 3.00 | True | 19.328 | 4.532 |
| 3 | 10 | 1.06 | True | 25.414 | 4.398 |
| 4 | 1 | 12.11 | True | 28.174 | 6.484 |
| 4 | 2 | 9.05 | True | 23.155 | 5.402 |
| 4 | 4 | 3.28 | True | 19.739 | 4.744 |
| 4 | 10 | 1.21 | True | 25.619 | 4.564 |
| 5 | 1 | 13.07 | True | 31.053 | 6.744 |
| 5 | 2 | 9.86 | True | 23.745 | 5.247 |
| 5 | 4 | 4.12 | True | 19.770 | 4.515 |
| 5 | 10 | 1.09 | True | 24.660 | 4.438 |

## Per-sigma summary

| sigma | median overshoot % | median IAE setpoint | median IAE disturbance | settled (out of valid) |
| --- | --- | --- | --- | --- |
| 1 | 12.11 | 28.174 | 6.484 | 5/5 |
| 2 | 9.05 | 23.155 | 5.247 | 5/5 |
| 4 | 3.28 | 19.739 | 4.517 | 5/5 |
| 10 | 1.09 | 25.414 | 4.398 | 5/5 |

Baseline (single outer SIMC PI loop) median d2 IAE: 35.279.

## plan_cascade (seed 1 when available)

- seed: 1
- tau_c_inner = 1.500 s, tau_c_outer = 15.000 s
- achieved separation sigma = 10.000
- warnings: none

## Failed seeds

- none, all seeds completed.

## Targets

- C1: MET - overshoot <= 20 % and settled in all valid seeds for sigma 10 and 4.
- C2: MET - median cascade IAE 4.398 <= 0.5 x baseline 35.279 = 17.640.
- C3 (informational): see the per-sigma summary table for sigma = 1, 2, 4, 10.
