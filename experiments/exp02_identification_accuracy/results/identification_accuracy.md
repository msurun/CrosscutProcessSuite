# Identification Accuracy Validation

Accuracy of FOPDT fits relative to noise-free step test baselines.

| Loop | Noise | Failed/No-win | Gain Err % (Med/P90) | Tau Err % (Med/P90) | Delay Err % (Med/P90) | Ref Gain | Ref SS-Gain | Ref Tau (s) | Ref Delay (s) |
|---|---|---|---|---|---|---|---|---|---|
| hpgr_press | low | 0 | 0.0 / 0.0 | 0.9 / 1.0 | 0.0 / 0.0 | 0.070 | 0.070 | 29.9 | 1.0 |
| hpgr_press | full | 0 | 6.4 / 20.9 | 8.0 / 132.7 | 0.0 / 6140.0 | 0.070 | 0.070 | 29.9 | 1.0 |
| mill_feed | low | 0 | 0.0 / 0.0 | 1.3 / 1.5 | 0.0 / 0.0 | 2.995 | 3.000 | 20.0 | 1.0 |
| mill_feed | full | 0 | 5.1 / 9.7 | 10.3 / 28.0 | 0.0 / 0.0 | 2.995 | 3.000 | 20.0 | 1.0 |
| cyc_water | low | 0 | 0.0 / 0.0 | 0.7 / 1.3 | 0.0 / 0.0 | 1.997 | 2.000 | 15.0 | 1.0 |
| cyc_water | full | 0 | 7.1 / 18.8 | 49.1 / 487.2 | 0.0 / 4990.0 | 1.997 | 2.000 | 15.0 | 1.0 |

## Limits

Reading (10 seeds per row, step size 8 % OUT, open loop). With low noise the identified gain is exact and the time constant is within about 1.5 %. With full noise the median gain error is 5-7 % (90th percentile up to 21 %) and the time constant error is 8-49 % at the median; its 90th percentile reaches 130-490 %, so one run in ten is unusable. The reference delay is one sample (1 s), so a relative delay error is not meaningful: 6000 % means about 60 s of absolute error. Treat the gain as usable at full noise, the time constant and the delay only with the fit check (R squared) next to them; averaging several steps would help and is not done here. Closed-loop data with the operator on is out of scope (see exp00).
