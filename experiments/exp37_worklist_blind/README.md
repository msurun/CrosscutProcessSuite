# exp37: sealed blind benchmark of the loop worklist (issue #85, protocol frozen before any sealed loop was analysed)

Why: the worklist (`crosscut_loops.worklist`, fed by KPI triage and stiction suspicion) is a rule of thumb. Its
rules and thresholds were set on synthetic loops and on SACAC/ISDB loops seen in exp10-exp24. This experiment
checks it once on a part of the public data that none of those experiments touched. Data are local only
(PROVENANCE.md: ISDB and SACAC carry no licence text; nothing is redistributed or committed except loop ids and labels).

## Sealed part (frozen 2026-11-18, before any analysis of these loops)

Excluded (touched by exp10-exp16, and in fact also exp17-exp24): every SACAC file used by exp10 (the 12 "stiction"
files), by exp12-exp16 (`exp12_stiction_scoreboard/labels.csv`: 19 loops, 31 files), and every ISDB loop that has a
row in `experiments/exp16_stiction_generalise/isdb_labels.csv` (untracked, local; sha256
d5518507e9ff2d73e240460644fd1d14123a767804ad60e4d1cdd8cd11eff283; 49 labelled rows, 44 independent).

Sealed SACAC files (9; all downloaded from https://sacac.org.za/resources/ on 2026-11-18, sha256):

| file | sha256 |
|---|---|
| plantwide-chemicals-bauer-2007.csv | bdf53c905c44b68ae8fe2fe130e59b8cebc2fd8966d7c7ad8d6e8d2d72f10fe4 |
| plantwide-minerals-brooks.csv | 77af225116cf7fd9d5f49a5e46f7a9b400216705ca4e6d9286c7be6f07bb7e50 |
| plantwide-minerals-lindner-2018.csv | 49b58503ebbbc51b3fbaf5948bec3bd59296a15497c4a93c4a67bd7c64ee0c5a |
| unknown-F-chemicals-thornhill-2003.csv | dceeec5bc3d213cf1a2d4172f72651ca50e2e4ff977d082ed5acd9a4897cc245 |
| unknown-F-minerals-bauer-2017.csv | f8a4935b0f8cfe7d83c1a6c3cbece16035fb17ec94b104580f7963b5419fa2fa |
| unknown-F-paper-horch-2003.csv | 05ea295b1a2846f732815a8fd878222cd742503cb70e1dcea016a6afd8e0d223 |
| unknown-L-oilgas-thornhill-2002.csv | 83f58a3209cbbbea4304ef81a46fb9196f82caab691c7d8504d4d343698b192c |
| unknown-P-oilgas-thornhill-2007-1.csv | 1a710843ab6ea5c9a39d47de56a833c2470eb732aac1a42a11a66a73847e17e0 |
| unknown-P-oilgas-thornhill-2007-2.csv | a3411dbdf8bce63166370ff74a7a3949fed6fa98af128d15af50a928d3d4722e |

Sealed ISDB part, defined by rule (`isdb10.mat`, sha256 4dd329b5af3f9bd6e9070bce3fd46e001bb763a21c9fb8be026571b9d364e7df,
zip sha256 3d79af7bc51d4597173771697d85412f658acac95df4c6139ca39eeb6a4a662b, both re-verified 2026-11-18):
every loop of `cdata.<section>.<loop>` that has an OP column, is not a synthetic test series, is not a `sacac-twin`
and has no row in `isdb_labels.csv`. The loop id list is written into this README (ids only) as soon as the .mat can
be read, before any detector runs on it. The ISDB manual's `BriefComments` of these loops are the only labels.

Known weakness, stated before the run: SACAC "unknown" and "plantwide" files carry no expert label, so they can only
be run for coverage and crash checks, not scored. The scored sealed part is therefore the unlabelled-in-exp16 ISDB
loops that have a provider comment; its size is expected to be small and may be too small for any conclusion.

## Scoring (frozen)

1. Ground truth per scored loop from the provider comment by a fixed rule: `stiction`, `tuning` (poor tuning,
   marginal stability, aggressive), `external` (disturbance, interaction, plant-wide oscillation), `other/none`
   (no oscillation, sensor, quantisation, dead zone). Ambiguous comments get `unclear` and are not scored.
2. Worklist run once, unchanged package code, rows from the existing overview/KPI triage path with default settings.
   A loop counts as "problem" when its true label is not `other/none`.
3. Metric A: rank of each true problem loop in the worklist (priority order), reported as the list of ranks, the
   median rank, and the fraction of problem loops in the top third (a random order gives one third).
4. Metric B: confusion matrix of the worklist action mapped to a class (`valve_test` -> stiction;
   `bump_test_and_retune`, `review_noise_response` -> tuning; `find_common_source`, `test_cycle_cause` -> external;
   `none` -> other) against the label. Counts only, Wilson 95 % intervals for the diagonal rate.
5. No tuning, no re-run, no threshold change after seeing results; a failure is reported as a failure. If fewer than
   10 scored loops exist the result is labelled "descriptive only, no pass/fail".

## Status

Data downloaded and hashed; the MATLAB file cannot be read in the available environment (scipy is not installed in
the project venv, and installing it was not permitted in this run). The run is therefore not executed here.
