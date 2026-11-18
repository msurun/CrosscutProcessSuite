# exp36: anomaly engine on public data (SKAB, Petrobras 3W) - issue #87

Status: protocol FROZEN before the first run. Module: anomaly (PCA T2/SPE, stuck-sensor rule, possible-ramp warning).
Owner decision 2026-11-17: validation uses public data only. This is a validation case, not a feature.

## Data (outside the repo, never committed)

- SKAB (Skoltech, github.com/waico/SKAB, commit b2c0d46c2971dcbfe71e26087b6d231998bb91c2, GPL-3.0): local only, nothing derived
  is committed (this folder holds only code, this protocol and aggregate numbers in results.md). 1 s sampling, 8 tags.
- Petrobras 3W Dataset 2.0.0 (github.com/petrobras/3W, commit c86cc7c70063646910be7292de8a54a6fb2a8399; data CC BY 4.0, code
  Apache-2.0). 1 s sampling, up to 18 usable tags per well, real wells only (file names `WELL-*`). Subset (seeded draw
  `numpy.random.default_rng(87)` over the sorted real-well files of each class): class 0 normal 12 files, class 4 flow
  instability 10, class 7 scaling in PCK 6, class 3 severe slugging 6 = 34 files, 29 MB. List in `w3_sel.txt` of the scratch
  folder and in results.md. PRONTO (Zenodo 1341583, 1.7 GB) is NOT part of this run: next step.
- Reading: pyarrow (pandas is not installed in the venv); data is read only, nothing from it is executed.

## Detector (one configuration, no tuning)

`crosscut_anomaly` as shipped: variance_fraction 0.90, alpha 0.99, min_consecutive 5, close_after 10, no dynamic lags,
stuck_samples 30. 3W: 10 s block means (sample_period_s 10), SKAB: native 1 s. Ramp warning: `unreliable_tags` rule of the API
(`ramp_min_hours` 0.25 on 10 s bins = 90 bins, share below `counter_like_share` 0.9); SKAB has no ramp evaluation.

## Split

- SKAB: fit on the first 70 % of `anomaly-free.csv`. Quiet test = last 30 % of it plus the samples before the first
  `anomaly == 1` of each of the 34 other files. Event test = every one of those 34 files; onset = first `anomaly == 1`.
- 3W, per well (wells with a class 0 file): fit on the first class 0 file of the well (sorted by name), rows with
  `class == 0` only. Tags = columns finite in >= 99 % of the bins of every file of that well and not constant in the fit data
  (at least 3 tags, else the well is skipped). Quiet test = the other class 0 files of that well, plus the `class == 0` stretch of
  class 7 files of that well. Event test = class 3, 4 and 7 files of that well; onset = first row with a class in {event,
  100 + event}. Wells without a class 0 file (14, 22, 24) cannot be fitted: reported, excluded from detection and false alarms.
- Class NaN rows (the 3600 s lead-in of 3W instances) are scanned but neither counted as quiet nor as event.

## Metrics and frozen targets

| ID | Metric | Target |
|---|---|---|
| F1 | False alarm events per quiet day (PCA and stuck events starting on quiet samples), pooled per dataset | <= 3 per day on 3W and on SKAB |
| F2 | Share of quiet samples inside an event | <= 0.02 |
| D1 | Detection rate: events starting at or after onset (first such event counts) | >= 0.70 per dataset |
| D2 | Median detection delay of detected files | <= 15 min (3W), <= 60 s (SKAB) |
| R1 | Ramp-warning precision: flagged ramp spans overlapping (+-1 bin) a real NaN gap or frozen stretch (>= 90 bins) of the same tag, over all flagged spans, on all 3W files | >= 0.50 (undefined if nothing is flagged) |

Ramp recall is reported but has no target. The ramp rule cannot see a NaN gap or an exactly constant stretch by construction
(linear ramps with non-zero slope only), so a recall of 0 is expected and is not hidden. The stuck rule is reported as counts
only (it is the exact-equality definition, so scoring it against frozen stretches would be circular).
Quiet days are extrapolated from short stretches (hours) and say so in results.md.

## Honesty rules

Run once, report all numbers whatever they are. A missed target stays missed; no threshold, tag set or binning change after the
first run (a change makes `exp36_v2`). Bug fixes that do not change a definition are listed in results.md.

Run: `python experiments/exp36_anomaly_public/run_exp36.py --data <scratch data_i87 folder>`; without the data it prints a
skip message and exits 0.
