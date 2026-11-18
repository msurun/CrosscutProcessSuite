# Results: tep_anomaly_v1 (run 2026-11-18)

Protocol `docs/benchmarks/tep_anomaly_v1.md`, frozen before the run, unchanged. Data: Rieth et al. 2017 (doi:10.7910/DVN/6C3JR1), converted from .RData with pyreadr; local only, not committed.
Train runs [45, 147, 148, 171, 191, 231, 300, 316, 353, 385], test runs [9, 44, 99, 132, 181, 230, 326, 379, 468, 498], PCA components k=31. The protocol sets no numeric pass/fail targets; these are the measured values.

| Fault | Detection rate | Mean delay (min) | False alarm rate |
|---|---|---|---|
| 1 | 1.0 | 6.3 | 0.0000 |
| 2 | 1.0 | 30.6 | 0.0000 |
| 3 | 0.0 | - | 0.0000 |
| 4 | 1.0 | 1.2 | 0.0000 |
| 5 | 1.0 | 0.9 | 0.0000 |
| 6 | 1.0 | 0.0 | 0.0000 |
| 7 | 1.0 | 0.0 | 0.0000 |
| 8 | 1.0 | 66.6 | 0.0000 |
| 9 | 0.0 | - | 0.0000 |
| 10 | 1.0 | 237.3 | 0.0000 |
| 11 | 1.0 | 42.6 | 0.0000 |
| 12 | 1.0 | 29.7 | 0.0000 |
| 13 | 1.0 | 96.0 | 0.0000 |
| 14 | 1.0 | 1.5 | 0.0000 |
| 15 | 0.0 | - | 0.0000 |
| 16 | 1.0 | 225.6 | 0.0000 |
| 17 | 1.0 | 66.9 | 0.0000 |
| 18 | 1.0 | 132.9 | 0.0000 |
| 19 | 0.7 | 1283.1 | 0.0000 |
| 20 | 1.0 | 146.4 | 0.0000 |
| fault-free | - | - | 0.0000 |

Faults 3, 9, 15 are not detected (known-hard faults for PCA-type detectors); fault 19 detected in 7 of 10 runs with a long delay. No false alarms before onset.
