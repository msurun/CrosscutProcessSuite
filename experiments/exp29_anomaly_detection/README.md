# exp29: PCA anomaly detection (Hotelling T2 and SPE) on the mill-circuit simulator with injected sensor faults

Protocol FROZEN 2026-10-22 BEFORE any module code exists and before any seed is run. A miss is logged, thresholds are not moved.
Test seeds are run once. Amendments only before the first development seed.

## Question
Does a PCA model fitted on fault-free operation raise few false alarms on fault-free data and detect drift and freeze of a process sensor in time, and does the contribution analysis point at the faulty tag? Synthetic data only; false-alarm behaviour on real plant data is not tested here (needs real quiet data, see OWNER_TASKS).

## Module under test (contract the harness codes against)
Package `anomaly/` (`crosscut_anomaly`): `AnomalyConfig(tags, variance_fraction=0.90, alpha=0.99, min_consecutive=5, close_after=10, mode)`; `fit_pca(x, config) -> PcaModel` (x: samples by tags, NaN rows dropped, standardised by training mean and standard deviation); `PcaModel.t2(x)`, `.spe(x)`, `.limits` (T2 limit k (n^2 - 1) / (n (n - k)) F_alpha(k, n - k); SPE limit by Jackson and Mudholkar 1979), `.contributions(x_row)` (per-tag share of SPE and of T2); `scan(model, t_s, x, quality, config) -> list[AnomalyEvent]` with event start, end, peak statistics, top contributing tags; rows with NaN or quality != 0 are skipped and counted, never imputed.

## Data (generator and harness written by a different model than the module author)
Plant `crosscut_sim` mill circuit, scenario `observational` (operator on), 10 s samples averaged to 60 s, PV tags only: hpgr_press, mill_feed, cyc_water, feed_moisture, p80, mill_power, hpgr_power and ore_hardness_est (8 tags). Fault injection with `crosscut_sim.faults` (`FaultyPlant`).
- Training record: 48 h fault-free, one per seed. Quiet test record: 72 h fault-free, same seed family (a separate run, seed + 1000 of the plant).
- Fault test record: 24 h, one fault at a random time between 6 h and 16 h (per seed) on a target tag; kinds cycle drift, freeze, spike, bad_quality, dropout; target tags cycle over the 8 tags.
  drift: magnitude = 1.0 standard deviation of the tag per hour (standard deviation from the fault-free training record), 6 h; freeze 2 h; spike: probability 0.02 per sample, magnitude 6 standard deviations, 1 h; bad_quality 1 h; dropout 1 h.

## Seeds
Development 29001..29060 (harness check, bugs only). Test quiet 29201..29260 (60 records). Test fault 29301..29399 (99 records, kinds cycling, about 20 per kind). Reserve 29401+.

## Frozen settings
`variance_fraction` 0.90, `alpha` 0.99, `min_consecutive` 5 samples (5 min), `close_after` 10 samples, 60 s samples. An alarm event starts when T2 or SPE exceeds its limit for `min_consecutive` consecutive valid samples.

## Pass criteria (test seeds)
| id | criterion |
|----|-----------|
| A1 | false alarm events on the quiet records: mean <= 1.0 per 24 h and no record above 3.0 per 24 h |
| A2 | drift detected (event starting within 180 min after fault onset, event overlapping the fault window) in >= 80 % of drift records |
| A3 | freeze detected (event starting within 60 min after onset) in >= 80 % of freeze records |
| A4 | for detected drift and freeze events, the faulty tag is among the top 2 contributors at the event peak in >= 70 % |
| A5 | rows skipped for quality or NaN are never imputed: the event count on bad_quality and dropout records equals the count on the same record with those rows removed (property check, 100 %) |

Reported, no target: detection rate and delay for spike, bad_quality and dropout; empirical exceedance of the limits on the training record (expected near 1 - alpha); share of valid rows; model rank k per seed.

## Decision rule
If A1 fails the module ships with a visible "false alarms not validated on real data; expect more" label and a longer default `min_consecutive`, chosen in a new frozen round on new seeds; if A2/A3/A4 fail they are documented misses and the GUI says which fault kinds are not reliably detected. Never iterate on test seeds.

## What this does not show
Faults are injected into a simulator whose normal behaviour is stationary and Gaussian-like (A1 in the assumption register); real plants have regime changes, grade changes and maintenance. A1 here says nothing about the false alarm rate on a real plant.

## Authorship
Module: Sonnet subagents under the lead; the lead re-derives the T2 and SPE limits against a textbook example. Generator and harness: an Opus subagent that does not edit `anomaly/`. Recorded after the run.

## Frozen files
(filled in by the harness commit before the first development seed.)

sha256 of the LF-normalised file (`tr -d '\r' < f | sha256sum`), 2026-10-22, before the first development seed:

| file | sha256 |
|------|--------|
| experiments/exp29_anomaly_detection/gen29.py | 6dfb0bcb41323eaea625f28f1175524b50be18d5effbc61a4b0abcf0642517b9 |
| experiments/exp29_anomaly_detection/exp29.py | 36513750cf69bfba1c907c437dbd575ab17aadf54b38c1aa48d3187e23b4ff8f |
| anomaly/src/crosscut_anomaly/pca_model.py | 721f687acfbb2876a30ac0046ec396ca0a983015c036191ed233fe172472f84a |
| anomaly/src/crosscut_anomaly/detect.py | 90f5efbad2b378768df1d3d1999ff0355aa3ac9b53400b3c6fbb0f6fdc0f7a21 |
| anomaly/src/crosscut_anomaly/config.py | 38c202a36a2051f9570fd128c047217f93a3167dde65066c0c45546a6c704cb2 |
| anomaly/src/crosscut_anomaly/distributions.py | 382e28fd8c1890cca8ba8131ecd5fa43144312da3ec6a62f5ebbb841970846fd |

Authorship note (harness): `gen29.py`, `exp29.py` and `test_exp29_smoke.py` were written by an Opus subagent that did not
edit `anomaly/`. Harness readings of points the protocol leaves open:
- Seeds: every seed s has its own training record (plant seed s); the quiet record uses plant seed s + 1000, the fault
  record plant seed s + 2000 (distinct from training). Test quiet seeds 29201..29260 give training + quiet, test fault
  seeds 29301..29399 give training + fault (kind = position mod 5 in the order drift, freeze, spike, bad_quality,
  dropout; tag = position mod 8 in the protocol order). Each dev seed 29001..29060 gives training + quiet + fault
  (same cycling, 12 records per kind).
- Onset: `default_rng([seed, 29])`, uniform in [6 h, 16 h], rounded to whole seconds. Magnitudes use the standard
  deviation (ddof 1) of the target tag over the 60 s training rows. Spike probability 0.02 applies per 10 s raw sample
  (the fault RNG draws once per 1 s plant step; one step in ten is sampled).
- 60 s rows are means of six 10 s samples stamped at the last sample (window start + 50 s); a NaN raw value makes the
  row value NaN (no imputation), the row quality is the worst raw quality over the window and all eight tags. Quality
  is passed to `scan` per row (the module accepts only a per-row quality vector).
- `fit_pca` is called as `fit_pca(x, config.tags, config.variance_fraction, config.alpha)`: the shipped signature
  differs from the `fit_pca(x, config)` of the contract above; the settings are the frozen defaults.
- Detection (A2, A3, reported kinds): the first event whose start lies in [onset, onset + 180 min] (drift) or
  [onset, onset + 60 min] (freeze, and the 1 h window of spike, bad_quality, dropout) and that overlaps the fault
  window; an event already open at the onset does not count. Delay = event start - onset.
- A4: top 2 of the contribution list of the statistic with the larger limit ratio at the event peak (T2 / T2 limit vs
  SPE / SPE limit); the SPE-only, T2-only and either-list shares are reported beside it.
- A5: the scan of the full record is compared with the scan of the record with every row that has a NaN or quality != 0
  removed: equal event count and, per event, equal start/end time, closure, sample count and start/end/peak row after
  mapping the reduced indices back. Checked on all fault records, judged on bad_quality and dropout.

## Robustness fixes (2026-10-22, after development seeds, before any test seed)
Changes in `anomaly/src/crosscut_anomaly/` (the sha256 values above are updated for `pca_model.py` and `detect.py`; `gen29.py`, `exp29.py` and the protocol are untouched):
1. Non-finite values (NaN and +-inf) are invalid everywhere: `fit_pca` drops such rows; `scan` counts them under `skipped_reasons['nan']` (the key is unchanged and now means non-finite); `t2`, `spe` give NaN and `contributions` raises `PcaModelError` for them, with no RuntimeWarning.
2. `scan` accepts `quality` per row (n,) or per tag (n, p; a row is invalid if any tag's quality != 0); any other shape, including the n == p ambiguity (2-D must be exactly (n, p)), raises `ValueError`.
3. `fit_pca`'s docstring documents the signature `fit_pca(x, tags, variance_fraction, alpha)`; the protocol's `fit_pca(x, config)` is provided by the thin helper `fit_from_config(x, config)` in `pca_model.py`.

Behaviour on finite data with per-row quality is unchanged and no setting or criterion changed: `pytest anomaly -q -p no:warnings` and `test_exp29_smoke.py` pass; new tests are in `anomaly/tests/test_anomaly_robustness.py`.

## Result (test seeds, first and only run, 2026-10-23; tables in results/test.md)
| id | value | criterion | met |
|----|-------|-----------|-----|
| A1 | false alarm events per 24 h on 60 quiet records: mean 2.128, max 4.667 | mean <= 1.0, max <= 3.0 | **no** |
| A2 | drift detected 20/20 (median delay 104 min) | >= 80 % | yes |
| A3 | freeze detected 2/20 (0.100) | >= 80 % | **no** |
| A4 | faulty tag in the top 2 contributors 0.864 of 22 detected (either statistic 0.955) | >= 70 % | yes |
| A5 | no imputation: 39/39 bad_quality and dropout records (60/60 other kinds) | 100 % | yes |

Reported: spike 0.10, bad_quality 0.00 and dropout 0.00 detection (the last two by design: those rows are skipped, not imputed); training exceedance T2 0.0099 and SPE 0.0087 against 0.01; 91 events started before the fault onset on the fault records.
Reading: PCA on the PV tags finds drift and points at the right tag, but (1) it raises about two false alarms per day on operator setpoint moves, which break the static correlation structure for a few minutes, and (2) it does not see a frozen sensor whose
value stays inside its normal range. Per the decision rule the module ships with a visible "false alarm rate not validated on real data; expect more" label. A round 2 (new frozen protocol, new seeds 29601+) should test three changes:
a dynamic PCA (lagged variables, Ku, Storer and Georgakis 1995), an explicit stuck-sensor rule (a tag exactly constant over N samples while the others vary) and a longer `min_consecutive`.

## Round 2 protocol (FROZEN 2026-10-23, before any round 2 code change is run and before any round 2 seed)
Round 1 missed A1 (false alarms from operator setpoint moves) and A3 (frozen sensor stays in its normal range). Changes under test, all in the module and all off by default so that round 1 stays reproducible:
1. Dynamic PCA (Ku, Storer and Georgakis 1995): `AnomalyConfig.dynamic_lags` = 2, so the model is fitted on each tag at lags 0, 1 and 2 samples (24 columns for 8 tags; rows lacking history are invalid); limits as in round 1 on the augmented matrix; contributions are summed over the lags of each tag.
2. Stuck-sensor rule: `AnomalyConfig.stuck_samples` = 15. A tag is stuck when its value is exactly unchanged for 15 consecutive valid samples while at least 3 other tags are not constant over the same samples; it gives an event of kind `stuck` naming the tag; rows are never imputed.
3. `min_consecutive` = 10 (round 1: 5); `close_after` 10, `alpha` 0.99 and `variance_fraction` 0.90 unchanged.
Same generator and harness code paths; the harness gets a `--round 2` switch changing only seed ranges, config values, the output names (results/dev2.md, test2.md and the *_runs.json) and the criteria below; hashes re-frozen. Seeds: development 29601..29660, quiet test 29701..29760, fault test 29801..29899. Round 1 seeds are spent; seeds 29401-29600 belong to exp30.
| id | criterion (test seeds) |
|----|-----------|
| B1 | false alarm events of any kind on the 60 quiet records: mean <= 1.0 per 24 h and no record above 3.0 per 24 h |
| B2 | drift detected within 180 min after onset in >= 80 % of drift records |
| B3 | freeze detected (an event of kind pca or stuck naming or overlapping the fault, starting within 60 min after onset) in >= 80 % of freeze records |
| B4 | for detected drift and freeze events, the faulty tag is among the top 2 contributors (stuck events name the tag directly) in >= 70 % |
| B5 | no imputation property as A5 (100 %) |
| B6 | `stuck` events on the quiet records: mean <= 0.1 per 24 h |
Reported, no target: detection rate and delay per kind and per rule (pca vs stuck), spike, bad_quality, dropout, number of valid rows lost to the lag history.
Decision: if B1 misses again the module keeps the visible "false alarm rate not validated on real data" label and its default `min_consecutive` stays 10; if B3 misses the GUI states that frozen sensors are not reliably detected. Development seeds may be used to fix bugs only; the three changes are frozen as written. Never iterate on test seeds.

### Round 2 frozen files
sha256 of the LF-normalised file (`tr -d '\r' < f | sha256sum`), 2026-10-23. Updated after the development fixes below (module commit 513c01c) and before any round 2 test seed. The first development run used exp29.py 4ac3389e..., pca_model.py 7c6a338c... and detect.py ee36c6d9...; the other three files are unchanged:

| file | sha256 |
|------|--------|
| experiments/exp29_anomaly_detection/gen29.py | 6dfb0bcb41323eaea625f28f1175524b50be18d5effbc61a4b0abcf0642517b9 |
| experiments/exp29_anomaly_detection/exp29.py | dc3e93609dd98fe01e907203622c9ab99f8d3137c796b5c17556761b5a65f620 |
| anomaly/src/crosscut_anomaly/pca_model.py | 1cf6a92c92497fd5d3a0c16e2005394dc6b772018108855392f3415bd81103bb |
| anomaly/src/crosscut_anomaly/detect.py | b342f3c7a1091e96380d63803db120755c0be34da0a70e28d46d75a49f3463a0 |
| anomaly/src/crosscut_anomaly/config.py | eb8bed70818011bd180c55ae18284bdd742e3c8b4dd01161cdf18a75fe9bd6b6 |
| anomaly/src/crosscut_anomaly/distributions.py | 382e28fd8c1890cca8ba8131ecd5fa43144312da3ec6a62f5ebbb841970846fd |

Harness readings for round 2 (`exp29.py --round 2`; round 1 output reproduces bit-exactly on dev seeds 29001, 29002, 29004 and 29005):
- Config: `AnomalyConfig(..., variance_fraction=0.90, alpha=0.99, min_consecutive=10, close_after=10, dynamic_lags=2, stuck_samples=15)`, model fitted with `fit_from_config`. Seed families as in round 1 (training = plant seed s, quiet s + 1000, fault s + 2000; kind and tag cycle by position in the family).
- B3 (and B2 and the reported kinds): the first event of either rule that starts in [onset, onset + window] and overlaps the fault window; the window already implies the overlap, so "naming or overlapping" adds nothing; whether a stuck hit names the faulty tag is reported (`stuck_names_tag`). Event start is the first sample of the run (for the stuck rule the first constant sample, confirmed 14 samples later).
- B4: a PCA hit uses the top 2 of the dominant statistic as in A4; a stuck hit counts when `stuck_tag` is the faulty tag.
- B5: as A5, with event kind and `stuck_tag` added to the per-event comparison. Training exceedance is taken over the rows with full lag history.

### Development round 1 of round 2 (2026-10-23, before any round 2 test seed)
The first round 2 development run (results/dev2.md, dev2_runs.json) found two module bugs. Both are fixed in `anomaly/` (commit 513c01c); the harness and the protocol are unchanged by them:
1. A held signal was flagged as stuck. `ore_hardness_est` is a held estimate that updates every 30 min, so it is exactly constant for 29 samples while the other tags move, and the stuck rule fired on it every 30 min on every record (48 stuck events per 24 h on all 60 quiet records; this drove the B1, B4 and B6 values). Fix: the stuck threshold is per tag, max(`stuck_samples`, ceil(1.5 x the longest exactly-constant run of that tag in the fault-free training data)). It is learned at fit time and stored in the model (`PcaModel.stuck_runs`; `fit_pca(..., stuck_samples=...)`, passed through by `fit_from_config`). The frozen text "exactly unchanged for 15 consecutive valid samples" is therefore now the floor of a per-tag threshold learned from fault-free training data.
2. Lag history bridged time gaps. The lag-augmented rows ignored the time stamps, so once invalid rows were removed a lagged row combined samples about 1 h apart. B5 failed on 1 of 24 records: a PCA event spanning a dropout gap had 107 samples on the full record and 109 on the record with the invalid rows removed. Fix: lagged history breaks when the time step exceeds 1.5 x `sample_period_s`; the affected rows are counted under `skipped_reasons['lag']`.

Development seeds 29601..29660 are spent. The rerun after the fixes reuses them as a bug check only (results/dev2b.md, dev2b_runs.json). No criterion and no seed range changed, and no setting changed apart from the stuck threshold rule above. Round 1 output still reproduces bit-exactly on dev seeds 29001, 29002, 29004 and 29005. The harness only gained `--name` (output base name) and now reports the per-tag longest constant training runs.

## Result round 2 (test seeds 29701..29899, first and only run, 2026-10-23; tables in results/test2.md)
| id | value | criterion | met |
|----|-------|-----------|-----|
| B1 | false alarm events on 60 quiet records: mean 1.789 per 24 h (all by the PCA rule), max 4.333 | mean <= 1.0, max <= 3.0 | **no** |
| B2 | drift detected 19/20 (median delay 116 min) | >= 80 % | yes |
| B3 | freeze detected 19/20 (19 by the stuck rule, median delay 1.2 min; PCA alone 2) | >= 80 % | yes |
| B4 | faulty tag in the top 2 (stuck events name it) 0.947 of 38 detected | >= 70 % | yes |
| B5 | no imputation: 39/39 bad_quality and dropout records (60/60 other kinds) | 100 % | yes |
| B6 | stuck events on quiet records: mean 0.000 per 24 h | <= 0.1 | yes |
Reported: spike 0.05; bad_quality and dropout 0.00 (by design: rows skipped, never imputed); SPE limit method empirical on all seeds (the Jackson-Mudholkar h0 is about 0.05 with 24 lagged columns); 84 events started before the fault onset on fault records.
Reading: the stuck-sensor rule solved freeze detection (0.10 to 0.95) and the false positives of the first attempt were traced to a held signal (ore_hardness_est updates every 30 min), so the stuck threshold is learned per tag from fault-free training data. False alarms of the PCA rule on operator setpoint moves
fell only from 2.13 to 1.79 per 24 h. The module ships with the visible label "false alarm rate not validated on real data; expect more", default `min_consecutive` 10, dynamic lags 2 and the stuck rule on. A third round would need a new frozen protocol and new seeds (candidates: smoothing statistics, excluding setpoint-move windows, a per-regime model). Line closed for tonight.

