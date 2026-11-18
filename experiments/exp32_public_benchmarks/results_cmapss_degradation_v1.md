# Results: cmapss_degradation_v1 (run 2026-11-18)

Protocol `docs/benchmarks/cmapss_degradation_v1.md`, frozen, unchanged. Data: NASA C-MAPSS (PCoE repository zip), local only, not committed. Predictor: the shipped ridge baseline with no operating-condition normalisation. The protocol sets no numeric targets; these are the measured values.

| Subset | Engines | RMSE | PHM08 score |
|---|---|---|---|
| FD001 | 100 | 22.66 | 1437 |
| FD002 | 259 | 31.79 | 19192 |
| FD003 | 100 | 22.44 | 1781 |
| FD004 | 248 | 35.49 | 12414 |

As the protocol anticipated, FD002/FD004 (six operating conditions) are clearly worse than FD001/FD003.
