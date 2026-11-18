# exp39: blind soft-sensor test on the public flotation data (issue #88)

Protocol FROZEN before any model is fitted and before any value of the sealed span has been looked at. A miss is logged,
thresholds are not moved. The sealed span is scored once.

## Data
- "Quality Prediction in a Mining Process" (E. M. Oliveira, Kaggle `edumagalhaes/quality-prediction-in-a-mining-process`),
  licence CC0: Public Domain. Provided locally by the owner, not committed, no derived data committed (docs/PROVENANCE.md row exists, exp39 added).
- File `MiningProcess_Flotation_Plant_Database.csv`, sha256 `ae0231a0bd2e14aac39cf978d81db6c71907a42aade19327816692c4e30cb956`
  (checked by the script before it reads anything).
- Loader: `experiments/exp04_public_flotation/flotation_public.py` (decimal commas, 20 s rows rebuilt inside each hourly label).

## Split (chosen from the date column only: min 2017-03-10 01:00, max 2017-09-09 23:00)
- SEALED: the last 4 full weeks of the file, Sunday 2017-08-13 00:00 to Saturday 2017-09-09 23:00 (label of the last hour).
  No value of this span was read before this README was committed.
- DEVELOPMENT: 2017-03-10 01:00 to 2017-08-12 23:00. All feature, lag and model choices use this range only.
  The script's `develop` mode slices the loaded arrays at the cut right after loading and never touches the rest.

## Task
- Target: `% Silica Concentrate`, one laboratory value per hour. Per hour the target is the first row of the hour (in 310 hours the file holds
  values interpolated inside the hour; the stamp value avoids mixing).
- Inputs allowed: process tags only, as hourly means of the 20 s rows: starch flow, amina flow, ore pulp flow, pH, density, 7 column air flows,
  7 column levels (19 tags). NEVER `% Iron Concentrate` (a lab result with the same stamp as the target). The feed lab columns
  (`% Iron Feed`, `% Silica Feed`) are lab results too and are not used either. Lab values enter only through the persistence baseline and the bias correction.
- Lab stamp meaning: the file label is taken as the START of the sampling hour (window 3600 s); the file does not say, a constant shift changes no result.
- Report delay assumption (ASSUMED, not in the file): a result is available 3600 s after the end of its window. The estimate for hour h is made
  at the end of hour h, so the newest lab known then is that of hour h-2.
- Missing values: hours absent from the file (318 hours, gaps up to 13 days) stay absent (NaN); no interpolation, no filling. An hour is
  usable when all 19 tags exist for it and for all its lags. Models predict only usable hours with a lab value.

## Methods (all scored on the same usable sealed hours)
- M0 persistence: the most recent lab value known at the end of hour h (hour h-2 or the latest earlier present hour, at any age).
- MM mean baseline: the mean of the development labs.
- M2 soft sensor: `crosscut_softsensor` PLS1 (`fit_pls`, `build_lagged`), fitted on development only, frozen; lags from {0}, {0,1 h}, {0,1,2 h},
  {0,1,2,3 h} and the number of components chosen on development (validation = last 20 % of development in time, then refit on all development). No refit on the sealed span.
- M3 corrected: M2 plus the EWMA (weight 0.3, first update takes the residual) of `lab - M2` over labs already known (delay rule above).
- Secondary, no target: persistence with delay 0 (hour h-1), to show how much the delay assumption matters.

## Metrics
RMSE, MAE and R2 of M0, MM, M2, M3 on the sealed span (R2 against the sealed mean, the usual definition), the ratios to M0 and MM, number of scored
hours.

## Frozen pass targets (chosen now, before any fit)
| id | target |
|----|--------|
| T1 | RMSE of M2 <= 0.90 x RMSE of M0 persistence (at least 10 % better than the last known lab value; a soft sensor that cannot beat this is not worth running) |
| T2 | RMSE of M2 <= 0.95 x RMSE of the mean baseline (it must explain at least some variance in a new period) |
| T3 | RMSE of M3 <= 1.05 x RMSE of M2 (the bias correction does not hurt) |
| T4 | at most 10 % of sealed hours that have a lab value are unusable; counted only over hours inside the file's span (exp31 round-2 rule: absent hours of a gap in the file are reported separately and not counted as unusable) |
| T5 | no leakage, checked by the script: no input window ends after the end of hour h, the target and the three lab columns are not among the inputs, the sha256 matches, the model is fitted before the sealed arrays are used |

The 10 % margin in T1 is arbitrary: it is about what an operator would need to notice, and a stricter or looser value would be equally unjustified.

## Decision rule
No retuning after the sealed numbers. A T5 miss is a defect (fix and re-run is allowed only because no sealed number may then have been used to decide
anything; the fix is documented). Everything else is reported as measured.

## Files
`exp39.py` (develop and sealed modes), `results.md` (written after the one sealed run), site example in `docs/examples/flotation_public/`.
