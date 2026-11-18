# exp36 results (protocol exp36_v1, run once 2026-11-18, issue #87)

Aggregate numbers only; no SKAB-derived data is committed (GPL-3.0, local use). Protocol and targets: README.md (frozen in
commit 9da4ee9). Run: `run_exp36.py --data <folder with skab/ and w3/>`.

## Outcome: every frozen target is missed

| ID | Target | SKAB | 3W | Met |
|---|---|---|---|---|
| F1 false alarm events per quiet day | <= 3 | 173.6 (44 events in 6.1 h, extrapolated) | 3.8 (7 events in 44.2 h, extrapolated) | no / no |
| F2 share of quiet samples inside an event | <= 0.02 | 0.86 | 1.00 | no / no |
| D1 detection rate | >= 0.70 | 3 of 34 = 0.09 | 3 of 10 = 0.30 | no / no |
| D2 median delay of detected files | <= 60 s SKAB, <= 15 min 3W | 381 s (3 files) | 5200 s = 87 min (3 files) | no / no |
| R1 ramp-warning precision | >= 0.50 | not evaluated | 99 of 241 flagged spans = 0.41 | no |

Stuck-rule events (counts only, no target): SKAB 7 in quiet stretches, 3W 16 in quiet files and 15 in event files.
Ramp recall is not claimed: 430 real NaN or frozen stretches (>= 90 bins) in 34 files, the ramp rule detects neither by design.

## Reading the numbers (what the data supports, no more)

- The detector, fitted on one normal record, treats most of a second normal record as anomalous. In 3W every quiet bin of the
  held-out normal files lies inside an event (F2 = 1.00) although only 7 events were opened: events stay open (close_after 10 bins)
  and cover whole files. In SKAB 86 % of the quiet samples (held-out part of anomaly-free plus pre-onset parts of the experiment files)
  are in events. Cause not diagnosed in this run (not tuned): the likely one is that a model fitted on 1.8 h (SKAB) or 5 h (3W) of one
  record does not cover the operating state of the next record (different day, load, valve position); the daily false alarm
  numbers are therefore not a stable rate but a measure of this shift. They are extrapolated from 6.1 h (SKAB) and 44 h (3W) of quiet data.
- Detection is low because events that start in the quiet part before onset are never credited (they are false alarms) and then
  the first event at or after onset must start there; this was not checked per file whether a record is already inside an open event at onset (likely given F2).
- 3W event files: 10 files could be scored (class 3: 1, class 4: 8, class 7: 1 of the 22 event files drawn); wells 10, 14, 22
  and 24 have no class 0 file in the subset, so their 12 event files were skipped.
- Ramp warning: 41 % of flagged ramp spans touch a real NaN or frozen stretch of the same tag (+-1 bin); the rest are slow
  drifts or counters that look linear at 10 s bins. 3W gaps are NaN, not interpolated, so the possible-ramp warning is the wrong
  detector for them; it does not meet R1 and is not validated against interpolated archive gaps by this data.

## Departures and bugs (listed, definitions unchanged)

- pandas is not installed in the venv: data read with pyarrow (parquet and csv).
- The first run counted alarm samples per event, so overlapping PCA and stuck events were double counted (3W share 1.13); changed to the
  union of events before the numbers above were recorded. F1, D1, D2 and R1 were not affected.
- Quiet stretches are short, and class 3/4 files have no certified quiet part (first 3600 s unlabelled), so they contribute no false alarms.
- Wells with one class 0 file (WELL-00004) are fitted on it and only their event file is scored.

## 3W subset used (real wells, seeded draw rng(87), 34 files, 29 MB)

- dataset/0/WELL-00001_20170218150135.parquet
- dataset/0/WELL-00001_20170520230000.parquet
- dataset/0/WELL-00002_20170209110022.parquet
- dataset/0/WELL-00002_20170211180129.parquet
- dataset/0/WELL-00002_20170622030105.parquet
- dataset/0/WELL-00002_20170625210127.parquet
- dataset/0/WELL-00002_20170809200000.parquet
- dataset/0/WELL-00004_20140807070055.parquet
- dataset/0/WELL-00005_20170402170043.parquet
- dataset/0/WELL-00005_20170403230043.parquet
- dataset/0/WELL-00006_20170207120228.parquet
- dataset/0/WELL-00006_20170507120135.parquet
- dataset/4/WELL-00001_20170316230000.parquet
- dataset/4/WELL-00002_20131215210107.parquet
- dataset/4/WELL-00002_20140125150112.parquet
- dataset/4/WELL-00002_20140126110241.parquet
- dataset/4/WELL-00004_20140806010107.parquet
- dataset/4/WELL-00005_20170616010033.parquet
- dataset/4/WELL-00005_20170625010059.parquet
- dataset/4/WELL-00005_20170625083000.parquet
- dataset/4/WELL-00010_20180416170029.parquet
- dataset/4/WELL-00010_20180423190021.parquet
- dataset/7/WELL-00001_20170226130146.parquet
- dataset/7/WELL-00022_20180912025800.parquet
- dataset/7/WELL-00024_20160708024918.parquet
- dataset/7/WELL-00024_20160712123044.parquet
- dataset/7/WELL-00024_20160720230624.parquet
- dataset/7/WELL-00024_20160828150330.parquet
- dataset/3/WELL-00001_20170320120025.parquet
- dataset/3/WELL-00014_20170918110103.parquet
- dataset/3/WELL-00014_20170921190114.parquet
- dataset/3/WELL-00014_20170922000042.parquet
- dataset/3/WELL-00014_20170922100042.parquet
- dataset/3/WELL-00014_20170925150218.parquet

## Next steps

- Diagnose the shift: fit on more than one record per well, scale per record, report events separately for PCA and stuck. A change makes exp36_v2.
- PRONTO (Zenodo 1341583, CC BY 4.0, 1.7 GB, Cranfield multiphase flow) not run here: next dataset.
- A dataset with interpolated gaps is needed for the possible-ramp warning (3W has NaN gaps only).
