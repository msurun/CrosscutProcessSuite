# exp37: anomaly engine on PRONTO multiphase flow data (SKAB/3W sibling of exp36) - issue #87

Status: protocol FROZEN before the first run. Same detector, same metrics and same targets as exp36 (README there), applied to the
Cranfield multiphase flow facility. Owner decision 2026-11-17: public data only; this is a validation case, not a feature.

## Data (outside the repo, never committed)

- PRONTO heterogeneous benchmark dataset, Zenodo record 1341583, licence CC BY 4.0 (Zenodo API license.id and README read),
  Stief, Tan, Cao, Ottewill, Thornhill, Baranowski, J. Process Control 79 (2019) 41-55, doi:10.1016/j.jprocont.2019.04.009.
- Only the DeltaV process-data csv files (1 s sampling) and the operation log (xlsx) were taken from the zip by HTTP range requests
  (about 21 MB of the 1.7 GB; the ultrasonic, high-frequency pressure, video and alarm files are not used). Scratch folder outside the repo.
- Files used: 0907Testday2 (air blockage and air leakage, 11:50-17:00), 0911Testday3 (air leakage, diverted flow, 10:00-17:00),
  0912Testday4 (normal and slugging, 10:00-14:00). 0626Testday5 (2018, other tag layout, not covered by the operation log) is excluded.
- Tags: the 19 process measurement columns after TIMESTAMP (Air In1 ... water tank level), minus columns constant in the fit window.
  The remaining 12 columns (controller OUT/SP/PV copies) are duplicates and are not used.
- Time axis: row i is second i after the first timestamp of the file (timestamps are printed to the minute only). Clock times
  come from the operation log (Excel day fractions). The log is sloppy; the transcription of blocks is in `run_exp37.py`
  (`BLOCKS`), ambiguous stretches are excluded, not guessed.

## Detector (one configuration, no tuning)

`crosscut_anomaly` as in exp36: variance_fraction 0.90, alpha 0.99, min_consecutive 5, close_after 10, stuck_samples 30, native 1 s.
Ramp warning: not evaluated (no NaN gaps in this data; R1 is not applicable).

## Blocks (from the operation log)

A block is a stretch with one valve position and one air/water set point. Kinds: `N` normal (valve at its no-fault position, health
label healthy/annular/normal), `F` fault (blockage valve V11 below 90 deg, leakage valve V10 above 0, diverted-flow valve U39
above 0), `S` slugging regime (reported separately, no target: a flow regime, not a fault), everything else unlabelled.
Set-point transitions are skipped by choosing block starts after the logged change. The first 120 s of every `N` block are not quiet.

## Split

- Per day one PCA model fitted on the first 70 % (by time) of the first `N` block of the day. Quiet test = last 30 % of it plus every
  other `N` block of that day (set-point change relative to the fit block is recorded: same or other set point).
- Event test = every `F` block: detected if an event starts inside the block (at or after block start), delay = start minus block start.
  Events that are already open at block start are not credited (as in exp36). `S` blocks are scored the same way, separately.

## Metrics and frozen targets (pooled over days)

| ID | Metric | Target |
|---|---|---|
| F1 | False alarm events per quiet day (events starting on quiet samples), extrapolated from the quiet hours | <= 3 per day |
| F2 | Share of quiet samples inside an event | <= 0.02 |
| D1 | Detection rate over `F` blocks | >= 0.70 |
| D2 | Median detection delay of detected `F` blocks (1 s data, blocks last 1-12 min) | <= 120 s |
| R1 | Ramp-warning precision | not applicable |

Also reported without target: quiet metrics split by same / other set point, share of `F` samples inside an event, stuck counts.

## Honesty rules

Run once, report all numbers. A missed target stays missed; no threshold, tag, block or window change after the first run
(a change makes `exp37_v2`). Bug fixes that do not change a definition are listed in results.md.

Run: `python experiments/exp37_pronto_public/run_exp37.py --data <scratch folder with the case-study tree>`; without the data it prints SKIP, exit 0.
