# exp39 results (one sealed run, 2017-08-13 to 2017-09-09; aggregate numbers only)

Development choice (before the sealed run, `frozen_config.json`): lag set {0 h} (validation RMSE on the last 20 % of development 1.116, 1.128, 1.136, 1.143 for
{0}, {0,1}, {0,1,2}, {0,1,2,3} h); PLS with 1 component on the sealed fit. No change after the sealed numbers.

| method | RMSE | MAE | R2 |
|---|---|---|---|
| M0 persistence (lab of h-2, delay assumption) | 0.8926 | 0.5844 | 0.419 |
| M0_delay1 persistence (lab of h-1, secondary) | 0.7362 | 0.4497 | 0.605 |
| MM mean of development labs | 1.1732 | 0.9582 | -0.004 |
| M2 PLS soft sensor (process tags only) | 1.1322 | 0.8818 | 0.065 |
| M3 M2 + EWMA lab bias correction | 0.8962 | 0.6339 | 0.414 |

672 scored hours (all 672 sealed hours have a lab value and usable inputs; no absent hours in the span).

| id | value | target | verdict |
|----|-------|--------|---------|
| T1 M2/M0 RMSE | 1.268 | <= 0.90 | MISS (M2 is 27 % worse than the last known lab value) |
| T2 M2/MM RMSE | 0.965 | <= 0.95 | MISS (3.5 % better than the mean, R2 0.065) |
| T3 M3/M2 RMSE | 0.792 | <= 1.05 | PASS (the correction helps, but only by following the lab: M3 = M0 within 0.4 %) |
| T4 unusable share | 0.000 | <= 0.10 | PASS |
| T5 no leakage | all three checks true | | PASS |

M2 against the faster persistence (delay 0): 1.538.

## Reading
On this record the process tags alone say almost nothing about the hourly silica concentrate in a new period: R2 0.065 against a mean baseline. The last lab value
is far better because the target is strongly autocorrelated, and the bias-corrected M3 gains only by turning into persistence. The honest verdict is
"this soft sensor is not worth running on this data"; the targets were not moved.

## What this data cannot show
- The report delay (3600 s) and the stamp meaning (start of hour) are assumptions; with delay 0 the persistence is stronger (0.736) and M2 is further behind.
- Hourly means of 20 s tags lose within-hour dynamics; the plant's mixing and residence times are unknown, only 0 h lags were chosen on development.
- One 4-week span of one plant; no process changes or lab method details; in 310 hours the concentrate columns hold values interpolated inside the hour.
- No setpoints or controller outputs, so no inference about what the operators did; no accuracy claim beyond this span; a model with a different structure
  (nonlinear, feed grades as inputs through their own report delay) was not tried and is not excluded.
