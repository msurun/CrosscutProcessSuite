# exp39 diagnosis — issue #154

The frozen model has no demonstrated deployment advantage. The most defensible explanation is
weak transferable information in contemporaneous hourly process means, compared with a recent lab
value that tracks the slowly varying target. Timing uncertainty, omitted disturbances and changing
regimes are plausible contributors, not established causes. This audit does not identify a unique
physical cause or justify a replacement model.

## Evidence boundary and reproduction

Read: this folder's `README.md`, `results.md`, `frozen_config.json`, and `exp39.py`;
the exp04 loader and README; and `softsensor/src/crosscut_softsensor/pls.py`.
The protocol, frozen configuration and original results are unchanged. Neither `develop` nor
`sealed` was executed. No held-out rows were loaded, fitted, scored or used for a new choice.
Previously published sealed aggregates below describe the failure only.

The README names an external CSV but supplies no absolute local path. No CSV was found in this
worktree; the standard Downloads location and the other checkout's data location were also absent,
and no FLOTATION/DATA_PATH environment setting was present. External storage was not exhaustively
searched. Consequently this is the requested committed-results/code fallback: no new raw-development
autocorrelation, lag correlations, feature ablation or regime statistics can honestly be reported.
The exp04 whole-record sampling observations are contextual evidence, not development-only estimates.

Run `python experiments/exp39_flotation_softsensor_blind/diagnose.py` from the repository root.
It reads only the recorded development RMSE paragraph, performs no model fitting, writes nothing,
and computes `100 * (candidate RMSE / zero-lag RMSE - 1)`:

| Maximum included lag (hours) | Development validation RMSE (silica percentage points) | Increase (%) |
|---|---:|---:|
| 0 | 1.116 | 0.000 |
| 1 | 1.128 | 1.075 |
| 2 | 1.136 | 1.792 |
| 3 | 1.143 | 2.419 |

These are rounded published scores on the final chronological 20% of development. Longer lag
sets can lose additional rows around gaps; no common-row comparison or uncertainty interval was
committed. The differences are descriptive, not evidence of statistical significance. Development
persistence scores were not committed, so the relative development skill cannot be reconstructed.

## What explains the loss, and what remains unresolved

**Lag and alignment.** The recorded development search argues against simply adding the tested
1–3 hourly histories to all tags. It does not rule out transport delay, tag-specific lags, longer
history, different aggregation windows or fractional-hour effects. `to_hourly` pairs the first
target row with process means across that labelled hour. If that target is a spot sample at the
start, later process observations are physically misaligned; if it represents a composite, the
correct window depends on collection metadata. Nonnegative lags establish computational causality
at the assumed end-of-hour estimate, not physical alignment or actual lab availability.
A uniform timestamp shift preserves the numerical pairing; changing lab stamp semantics relative
to process windows does not. The README's constant-shift statement cannot validate that pairing.
The h-2 availability rule is a frozen assumption, not a verified reporting schedule.

**Lab rate versus process dynamics.** One lab per hour is not 180 independent labels, even though
process rows occur every 20 seconds. Hourly means remove within-hour variation and event order.
The exp04 README reports oscillation periods from 160 to 57,000 seconds across the full record;
some dynamics are faster than hourly resolution, but those observations do not establish their
relationship to silica. Reconstructed within-hour times are not independent measured timestamps.
The reported 310 hours of within-hour concentrate interpolation further weaken a literal sampling
interpretation. Selecting the first row avoids averaging synthetic target trajectories; it does
not recover missing sample provenance. We cannot estimate a residence time or aliasing effect here.

**Autocorrelation favours persistence.** The committed sealed comparison is M0 RMSE 0.8926 versus
M2 1.1322; the shorter-delay baseline scores 0.7362. Those existing results establish strong value
in recent labs, consistent with target continuity. For a stationary target with variance sigma²,
lag-k persistence has expected squared error `2 * sigma² * (1 - rho(k))`; high autocorrelation
therefore makes persistence hard to beat. This identity is explanatory, not a fitted stationary
model or a measured development autocorrelation. Interpolation can also induce apparent continuity.
M3 scores 0.8962 by incorporating delayed lab residuals, almost matching M0. This suggests that lab
history supplies useful missing state, but aggregate similarity does not prove that M3 predictions
equal persistence or that the process features have zero incremental value.

**Feature set and model capacity.** The 19 inputs comprise reagent flows, pulp flow/pH/density,
and seven air flows plus seven levels. The one-component sealed PLS fit is a linear projection;
it cannot express nonlinear grade/reagent interactions without added features. Feed grade, ore
properties, setpoints, controller outputs and operating mode are absent from this predictor.
Excluding simultaneous concentrate assays and undelayed feed labs was appropriate for leakage
control. A future feed-grade feature needs its own acquisition and release times. The full-record
exp04 finding of two air flows with roughly 54% flat samples motivates instrument screening, but
does not prove those signals were faulty or harmful on development. No ablation establishes a
particular missing feature or nonlinear method as the cure.

**Regime shifts and validation.** A frozen fit across months can encounter changes in ore, reagent
policy or instrumentation. The committed results contain no per-regime development scores, so
drift is unmeasured. Development zero-lag validation RMSE 1.116 and sealed RMSE 1.1322 alone do
not demonstrate a large shift: their target variability and scored populations differ. The code
selects lags using a chronological outer split, but `cv_split` selects PLS components using
contiguous validation blocks with training on both sides. Its exclusion gap equals the longest
lag (zero for the selected candidate); it is not a forward deployment simulation and need not
remove target autocorrelation. This is a selection limitation within development, not evidence
of held-out leakage. `predict_rows` also does not enforce model validity flags, so complete inputs
and T4 passing do not establish in-domain operation.

## Validation and scope

The audit has five unit tests covering extraction, malformed evidence and ratio arithmetic.
The required worktree gate, with this checkout's PYTHONPATH, passed:
`bash C:/Users/regiz/cc-wt-check.sh softsensor/tests experiments/exp39_flotation_softsensor_blind/test_diagnose.py`
— 118 tests passed, including the five audit tests; ruff passed.
`fk check` could not initialize because access to `C:/Users/regiz/.config/foremankit` was denied;
no permission bypass or paid call was attempted. Graphify query was attempted before source
exploration, but this checkout has no graph. No graph or implementation log was written because
the task restricts changes to this experiment folder. No new published modelling method is
implemented; the script only audits existing aggregate arithmetic.

## Ranked candidates for a NEW experiment line, and #155 gates

All proposals below require development evaluation first, a separately frozen protocol and a
genuinely new untouched holdout. The exp39 sealed span is permanently spent; it cannot select
lags, structures, thresholds or regimes for the new line.

1. **Resolve timing before adding capacity.** Obtain sample-window, timestamp, residence-time and
   report-release metadata. On development only, compare causal windows and physically justified
   tag-specific lags on identical scored rows; report availability age and gaps. #155 must block
   ambiguous timing and future/unreleased lab inputs, and show the assumed estimation horizon.
2. **Measure incremental skill over lab history.** On forward development splits, compare the
   process model, age-aware persistence, autoregression, and process-plus-delayed-lab residual
   models at the same information cutoff. Report target ACF, change prediction and lab-age strata.
   #155 must require a preregistered material advantage over the strongest available causal
   baseline, not merely over the mean or uncorrected PLS. A successful bias correction alone is
   insufficient evidence of process-feature value.
3. **Recover informative dynamics and disturbances.** Compare causal subhour summary windows,
   reagent-to-throughput relationships, instrument screening and feed assays released on time.
   Use development ablations before choosing interactions or nonlinear alternatives. #155 must
   require tag roles, units, quality, missingness, sample provenance and availability contracts;
   unavailable features must cause a visible refusal or explicit validated fallback.
4. **Test stability across regimes and time.** Use rolling-origin development evaluation with
   train-only scaling, nested forward component selection, gap handling and dependence-aware
   uncertainty. Define regimes from available process information and inspect residual bias and
   validity coverage per regime. #155 must gate the deployment domain, minimum usable coverage,
   stale labs and drift; any update policy must itself be frozen and validated causally.
5. **Validate the selected candidate once on fresh evidence.** Freeze baseline definitions,
   common-row masks, minimum sample size, uncertainty method, practical skill margin and coverage
   limits before opening a new holdout. Obtain an independent period or public dataset if no
   genuinely untouched period exists. #155 must keep presets experimental until these gates pass
   and explicitly refuse deployment when no advantage is demonstrated: “Deployment refused:
   no validated advantage over the available lab baseline.” Exp39 supplies no qualifying preset.
