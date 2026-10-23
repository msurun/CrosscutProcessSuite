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
