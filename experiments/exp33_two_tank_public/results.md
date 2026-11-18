# exp33 results (run 2026-11-18, protocol and targets as frozen in README.md, commit 3f983b9)

Data: Zenodo 10.5281/zenodo.17688566 v2.0, CC BY 4.0, 25 runs read from a scratch folder (not in the repo).
Command: `run_exp33.py --data <scratch>/x`. The tables below are the script output, unedited except the model column
shortened. Targets were not changed after the run.

| target | outcome | evidence |
|---|---|---|
| D1 | MET | min share 1.000 |
| S1a | MET | IAE 502.5 (500), settle 300.0 s (299.6), os 0.000 |
| S1b | MET | max rel diff 2.22e-16 |
| M1 | MET | 25/25 runs |
| I1 | NOT MET | identified 10/10, within 30% 7, median k 0.0683 |
| I2 | MET | 10/10 with delay in [1, 3] s |
| A1 | NOT EXERCISED | assessed 1, in band 0 |
| A2 | MET | 10/10 |

| run | sat share | monitor sat | class | iae/h rel | steps | med IAE | med OS | med settle s |
|---|---|---|---|---|---|---|---|---|
| Baseline_100pct | 0.000 | 0.000 | oscillating | 2.2e-16 | 16 | 492 | 0.265 | 1798 |
| Baseline_10pct | 0.000 | 0.000 | oscillating | -2.2e-16 | 16 | 446 | 0.167 | 1798 |
| Baseline_20pct | 0.000 | 0.000 | poor_performance | 0.0e+00 | 16 | 422 | 0.137 | 1796 |
| Baseline_30pct | 0.000 | 0.000 | oscillating | 0.0e+00 | 16 | 459 | 0.157 | 1798 |
| Baseline_40pct | 0.000 | 0.000 | oscillating | -1.1e-16 | 16 | 443 | 0.147 | 1798 |
| Baseline_50pct | 0.000 | 0.000 | oscillating | 0.0e+00 | 16 | 441 | 0.206 | 1795 |
| Baseline_60pct | 0.000 | 0.000 | poor_performance | 0.0e+00 | 16 | 486 | 0.206 | 1794 |
| Baseline_70pct | 0.000 | 0.000 | poor_performance | 0.0e+00 | 16 | 515 | 0.284 | 1795 |
| Baseline_80pct | 0.000 | 0.000 | poor_performance | 0.0e+00 | 16 | 513 | 0.265 | 1798 |
| Baseline_90pct | 0.000 | 0.000 | oscillating | 0.0e+00 | 16 | 521 | 0.216 | 1799 |
| Disturbance_HighOutflow_100pct | 0.185 | 0.189 | poor_performance | 0.0e+00 | 16 | 3307 | 1.167 | 1800 |
| Disturbance_HighOutflow_10pct | 0.273 | 0.276 | saturated | 0.0e+00 | 16 | 4617 | 1.167 | 1800 |
| Disturbance_LowOutflow_40pct | 0.000 | 0.000 | poor_performance | 0.0e+00 | 16 | 463 | 0.196 | 1797 |
| Disturbance_LowOutflow_50pct | 0.000 | 0.000 | poor_performance | 0.0e+00 | 16 | 555 | 0.373 | 1798 |
| PassiveOutflow_0pct | 0.170 | 0.176 | ok | 0.0e+00 | 16 | 3948 | 1.216 | 1800 |
| PassiveOutflow_100pct | 0.801 | 0.804 | saturated | 0.0e+00 | 16 | 56355 | 0.000 | 1800 |
| PassiveOutflow_10pct | 0.279 | 0.283 | saturated | 2.2e-16 | 16 | 4711 | 1.422 | 1800 |
| PassiveOutflow_20pct | 0.388 | 0.392 | saturated | 0.0e+00 | 16 | 6980 | 0.755 | 1800 |
| PassiveOutflow_30pct | 0.526 | 0.528 | saturated | -1.1e-16 | 16 | 14615 | 0.255 | 1800 |
| PassiveOutflow_40pct | 0.579 | 0.582 | saturated | -1.1e-16 | 16 | 23719 | 0.000 | 1800 |
| PassiveOutflow_50pct | 0.577 | 0.580 | saturated | 0.0e+00 | 16 | 14745 | 0.000 | 1800 |
| PassiveOutflow_60pct | 0.628 | 0.630 | saturated | 0.0e+00 | 16 | 25768 | 0.000 | 1800 |
| PassiveOutflow_70pct | 0.675 | 0.677 | saturated | 0.0e+00 | 16 | 34342 | 0.000 | 1800 |
| PassiveOutflow_80pct | 0.733 | 0.735 | saturated | 0.0e+00 | 16 | 38741 | 0.000 | 1800 |
| PassiveOutflow_90pct | 0.769 | 0.773 | saturated | 0.0e+00 | 16 | 49032 | 0.000 | 1800 |

| run | gain | tau s | delay s | k=gain/tau | note |
|---|---|---|---|---|---|
| Baseline_100pct | 5.708 | 93.56 | 1.0 | 0.061 |  |
| Baseline_10pct | 9.792 | 88.64 | 1.0 | 0.11 |  |
| Baseline_20pct | 9.825 | 92.51 | 1.0 | 0.106 |  |
| Baseline_30pct | 9.466 | 89.59 | 1.0 | 0.106 |  |
| Baseline_40pct | 8.651 | 100.6 | 1.0 | 0.086 |  |
| Baseline_50pct | 8.352 | 112.7 | 1.0 | 0.0741 |  |
| Baseline_60pct | 6.293 | 108.3 | 1.0 | 0.0581 |  |
| Baseline_70pct | 6.688 | 108.1 | 1.0 | 0.0619 |  |
| Baseline_80pct | 6.113 | 97.76 | 1.0 | 0.0625 |  |
| Baseline_90pct | 5.747 | 96.92 | 1.0 | 0.0593 |  |

| run | status | conf | rec | used/found | logged Kc | logged Ti | SIMC Kc | SIMC Ti | band | model |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline_100pct | low_confidence | low | bump_test | 8/16 | 0.711 | 5.24 | nan | nan | False | K=4.801143194722489 tau=84.77623538977655 s theta=0.8055555555555556 s |
| Baseline_10pct | low_confidence | low | bump_test | 8/16 | 0.338 | 3.63 | nan | nan | False | K=10.092462807161404 tau=71.78069503741791 s theta=0.7991452991452992 s |
| Baseline_20pct | low_confidence | low | bump_test | 8/15 | 0.313 | 3.36 | nan | nan | False | K=7.666179612974945 tau=68.36780020488372 s theta=0.9686609686609685 s |
| Baseline_30pct | low_confidence | low | bump_test | 8/16 | 0.299 | 3.38 | nan | nan | False | K=7.202441280504642 tau=69.85325874858079 s theta=1.5769230769230769 s |
| Baseline_40pct | low_confidence | low | bump_test | 8/16 | 0.374 | 3.93 | nan | nan | False | K=7.740393637472091 tau=85.6689090154572 s theta=1.5455840455840455 s |
| Baseline_50pct | low_confidence | low | bump_test | 8/16 | 0.413 | 4.1 | nan | nan | False | K=7.973554440131768 tau=105.33958195106281 s theta=0.5341880341880343 s |
| Baseline_60pct | low_confidence | low | bump_test | 8/15 | 0.51 | 3.89 | nan | nan | False | K=0.08583590297535748 tau=22.2943433142154 s theta=40.0 s |
| Baseline_70pct | low_confidence | low | bump_test | 8/16 | 0.758 | 5.66 | nan | nan | False | K=6.412396766479334 tau=100.39911703993457 s theta=0.5 s |
| Baseline_80pct | ok | medium | retune_cautiously | 8/16 | 0.685 | 5.09 | 5.93 | 10.5 | False | K=5.5257779520279735 tau=86.33215765605269 s theta=0.5484330484330484 s |
| Baseline_90pct | low_confidence | low | bump_test | 8/16 | 0.621 | 4.5 | nan | nan | False | K=4.832901813752388 tau=91.6992769319725 s theta=0.5 s |

## Outcome per target

- D1 met: the logged Kp matches the Dahlin formula on every row, so the Kp/Ki mapping (Ti = Kp/Ki) is read correctly.
- S1a met, S1b met: the KPI function matches the analytic first-order values (IAE 502.5 vs 500 is the discrete sum; settling 300.0
  vs 299.6 s) and `window_metrics.iae_per_h` equals the independent reference to rounding on all 25 runs.
- M1 met: monitor saturation within 0.01 of the independent share on 25/25 (it reads 0.003-0.006 higher: it uses a
  tolerance band at the limits) and "saturated" appears exactly where the share exceeds 0.2.
- I1 NOT MET: all 10 Baseline runs were identified, but only 7 have `k = gain/tau` within +-30 % of the median 0.068.
  The three outliers are the 10 to 30 % valve openings (k 0.106-0.11, 1.6x the 100 % opening): the Baseline runs are
  not the same plant, k falls as the electrovalve opening rises (0.11 at 10 %, 0.06 at 60-100 %). The premise of
  the target (repeats of one plant) was wrong for this dataset, so the miss is reported as a miss.
- I2 met: all 10 identify delay 1.0 s (the lower bound of the engine, `max(d, 1)` samples); truth is 2 samples
  (the target window [1, 3] s was satisfied at its edge, so I2 is weak evidence).
- A1 NOT EXERCISED: only 1 of 10 runs reached medium confidence (Baseline_80pct); 9 are low confidence
  ("bump_test", no settings given). The single assessed run is outside the band: SIMC Kc 5.9, Ti 10.5 s against logged
  Kc 0.69, Ti 5.1 s. The target needed at least 3 assessed runs.
- A2 met: all four vendor forms of the logged tuning equal their hand formulas.

## Findings (generic engine gaps, no plant-specific change made)

1. **Settling KPI vs quantisation.** The level is 8-bit quantised (0.39 % of span) and the step is 5 %, so the 5 % settling
   band (0.25 %) is below one quantisation step; settling time reads about 1800 s (never settled) on 8 of 10 Baseline runs.
   A settling KPI needs a band of at least a few quantisation steps; `quantisation_ratio` exists in `health_kpis` but is
   not used by any step KPI. Not implemented (the KPI function lives only in this experiment).
2. **Monitor class on a staircase.** 5 of 10 Baseline runs are classified "oscillating" and 4 "poor_performance" with
   median overshoot of 14-28 %, plus the 0.98 mm quantised level; with a logged Ti of 3-5 s on a lag-dominated level plant
   this can be a real limit cycle, but the classification was not checked against a reference here. Treat as an open
   question, not as a verdict on the detector.
3. **History tuning is mostly unconfident on this data.** `tune_from_history` uses 8 windows of 16 (MAX_WINDOWS) and gets
   low confidence in 9 of 10 runs; one run (Baseline_60pct) fitted a 40 s delay with gain 0.09, the others tau 68-105 s,
   delay below one sample. No settings are issued for low confidence, which is the intended guard.
4. **Medium-confidence recommendation is far from the logged tuning** (Kc about 9x, Ti 2x). Whether it is safe on the plant
   is not testable here (no plant to run it on); exp26 validated medium-confidence safety on simulated integrators only.
5. **Saturation at 17 %:** PassiveOutflow_0pct has 17 % pump saturation, a sensor-dropout share and 120 % overshoot but is
   classified "ok" because the saturation limit is 20 %. This is the documented default, listed for the record.
6. **Delay floor.** `identify_fopdt_closed_loop` and `tune_from_history` cannot report a delay below one sample; a
   2-sample true delay was reported as 1.0 s.
