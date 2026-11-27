# exp39 diagnosis — issue #154

The frozen model has no demonstrated deployment advantage. The most defensible explanation is
weak transferable information in contemporaneous hourly process means, compared with a recent lab
value that tracks the slowly varying target. Timing uncertainty, omitted disturbances and changing
regimes are plausible contributors, not established causes. This audit does not identify a unique
physical cause or justify a replacement model.

## Evidence boundary and reproduction

Read: this folder's `README.md`, `results.md`, `frozen_config.json`, and `exp39.py`;
the exp04 loader and README; and `softsensor/src/crosscut_softsensor/pls.py`.
The protocol, frozen configuration and original results are unchanged. Part 1 executed neither `develop` nor
`sealed`; part 2 (below) runs development-only analyses. No held-out rows were fitted, scored or used for a new choice.
Previously published sealed aggregates below describe the failure only.

The README names an external CSV but supplies no absolute local path. No CSV was found in this
worktree; the standard Downloads location and the other checkout's data location were also absent,
and no FLOTATION/DATA_PATH environment setting was present. External storage was not exhaustively
searched. Part 1 was therefore the committed-results/code fallback; the data became available for part 2,
which supplies the raw-development statistics.
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

## Part 2: development-only analyses on the data (issue #154)

Run: `python experiments/exp39_flotation_softsensor_blind/diagnose_dev.py <csv>` (sha256 checked).
**Sealed span guard:** `development_hourly` slices every hourly array at `exp39.cut_hour()`
(first sealed hour, 2017-08-13 00:00) immediately after the hourly aggregation and
`assert_development_only` raises if any array is longer; the sealed arrays are dropped and never
fitted, scored or inspected. (The CSV is parsed whole by the frozen loader, so the file bytes pass
through memory, but no sealed value is kept or used.) Protocol, `frozen_config.json` and
`results.md` are unchanged. Development has 3,743 hourly slots, 3,425 with a lab value.
"Validation" below is the protocol's own: PLS fitted on the first 80% of development, scored on
the last 20% (hours 2,994 onward, 2017-07-12 19:00 to 08-12).

**Target autocorrelation and the persistence identity.** rho(1h)=0.768, rho(2h)=0.662,
rho(3h)=0.583, rho(6h)=0.366, rho(12h)=0.203, then a plateau near 0.18-0.19 out to 24 h (slow
level shifts, not a decay to zero). The measured mean squared difference of lab values k hours
apart matches `2 s2 (1 - rho_k)` within 0.3% at every lag 1-24 (ratio 0.999-1.003), so the
identity is numerically confirmed on development: persistence error is fixed by the ACF.
Persistence at the assumed h-2 delay therefore implies RMSE about sqrt(0.85)=0.92.

**Baselines vs PLS on identical rows** (749 validation rows with every method defined):

| method | RMSE (silica pp) |
|---|---:|
| M0 persistence, lab of h-2 | 0.912 |
| M0 persistence, lab of h-1 | 0.728 |
| mean of training labs | 1.072 |
| M2 PLS (3 components when refit here) | 1.116 |
| M3 PLS + EWMA bias | 0.923 |

On development the PLS is worse than the mean and 22% worse than the delayed-lab baseline, i.e.
the sealed failure (M2 1.132 vs M0 0.893) was already visible in development: the frozen lag
search compared only PLS variants, never persistence. The PLS has no skill over the training mean
in the last 20% of development; M3 again equals persistence (+1%).

**Per-tag lag cross-correlation (hourly means, development, k=0..6 h; level / first difference).**
Level correlations are weak (|r| <= 0.26) and almost flat across k=0-6 (for example column 01
air flow -0.25, -0.26, -0.26, -0.26, -0.26, -0.25, -0.25), so there is no sign of a transport
delay peak; they describe slow co-drifting between tags and silica, not a short-lag causal
channel. After first-differencing both series every correlation is within +-0.05 at every lag:
hour-to-hour changes of the tags carry no detectable linear information on hour-to-hour changes
of silica, for any lag 0-6 h. The strongest level tags are air flow columns 01-03 (about -0.25),
levels of columns 04, 05, 07 (-0.16 to -0.19 at k=0, shrinking with lag) and pH (-0.15).

**Feature ablation** (validation RMSE on the same 749 rows; PLS refit, components re-chosen):

| inputs | tags | RMSE |
|---|---:|---:|
| all | 19 | 1.116 |
| drop reagents | 17 | 1.093 |
| drop pulp | 16 | 1.120 |
| drop air | 12 | 1.039 |
| drop levels | 12 | 1.081 |
| only reagents | 2 | 1.041 |
| only pulp | 3 | 1.060 |
| only air | 7 | 1.138 |
| only levels | 7 | 1.060 |

Removing any single group except pulp helps; air flows hurt most (dropping them is best, 1.039,
about 3% better than the mean), and air alone is worst (1.138). Nothing beats the mean by more
than 3% and nothing approaches persistence (0.912). These are single fits on one 20% block, not
repeated or significance-tested, and the groups were not chosen for use: this is a diagnostic
(the air flows carry the largest level correlations yet do not transfer, consistent with
spurious drift association, and two of them are the flat-signal tags of exp04).

**Per-month residual bias (PLS pred - lab, fit on first 80%; March to 12 July in-sample, rest validation).**

| month | mean residual | residual RMSE | hours |
|---|---:|---:|---:|
| 2017-03 | -0.152 | 1.294 | 209 |
| 2017-04 | -0.007 | 1.065 | 720 |
| 2017-05 | -0.053 | 1.073 | 744 |
| 2017-06 | +0.073 | 0.865 | 720 |
| 2017-07 | +0.095 | 1.070 | 744 |
| 2017-08 | +0.229 | 1.074 | 288 |

Bias is small in every month (<= 0.23 pp) but moves monotonically from negative to positive, and
residual RMSE stays about 1.07 even on in-sample months (June 0.86 is the only lower one); August is validation-only. The
error is therefore mostly unexplained within-month variance, not a month-level offset: a
bias correction fixes only a small part, which is why M3 only reaches persistence.

**Evidence update.** (a) The ACF identity is now measured, not assumed. (b) Persistence beats
the PLS already on development by about 20%, so the frozen choice rule (PLS variants only)
could never have flagged the result. (c) No lag structure of 0-6 h appears in the correlations,
so "tag-specific lags" is weakened as a cure; the loss is not primarily alignment of the
hourly means (but sample-window semantics remain untested). (d) Process-to-silica association
is slow drift, not hour-level dynamics, and generalises poorly between months. (e) The air-flow
group is actively harmful for this linear model. These findings are descriptive, from one split.

## Ranked candidates for a NEW experiment line, and #155 gates

All proposals below require development evaluation first, a separately frozen protocol and a
genuinely new untouched holdout. The exp39 sealed span is permanently spent; it cannot select
lags, structures, thresholds or regimes for the new line.

1. **Resolve timing before adding capacity** (part 2: no 0-6 h lag structure in the correlations, so expect little from lags alone). Obtain sample-window, timestamp, residence-time and
   report-release metadata. On development only, compare causal windows and physically justified
   tag-specific lags on identical scored rows; report availability age and gaps. #155 must block
   ambiguous timing and future/unreleased lab inputs, and show the assumed estimation horizon.
2. **Measure incremental skill over lab history** (part 2: persistence already beats PLS by ~20% on development; promote this item to first). On forward development splits, compare the
   process model, age-aware persistence, autoregression, and process-plus-delayed-lab residual
   models at the same information cutoff. Report target ACF, change prediction and lab-age strata.
   #155 must require a preregistered material advantage over the strongest available causal
   baseline, not merely over the mean or uncorrected PLS. A successful bias correction alone is
   insufficient evidence of process-feature value.
3. **Recover informative dynamics and disturbances** (part 2: first-difference correlations are ~0, air-flow inputs hurt; screen instruments first). Compare causal subhour summary windows,
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
