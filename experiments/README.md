# Experiments index and status

This index covers all 34 directories under `experiments/`. Closed experiments stay in place and are not moved: their paths are frozen, some files are sha256-frozen, and exp15 and exp16 import from each other.
New experiments must serve a product feature named in `docs/PRODUCT.md`; a validation case is not a feature.

| Experiment | Module | Status | What it decided |
|---|---|---|---|
| exp00_sp_vs_mv | foundations | active | Confounding is real; fast variation is needed to identify gain. |
| exp01_stiction_validation | loop monitoring/tuning | closed | Stiction line closed; OUT-shape detector acceptance run done. |
| exp02_identification_accuracy | loop monitoring/tuning | active | FOPDT identification is accurate on noise-free simulated steps (docstring only, no README). |
| exp03_retune | loop monitoring/tuning | active | SIMC/AMIGO retune validated on a detuned mill loop; overshoot diagnosis (docstring only, no README). |
| exp04_public_flotation | foundations | active | PV-only checks on public flotation data need a setpoint or amplitude limit. |
| exp05_timing_faults | foundations | active | Loop checks pass jitter and mode-flip targets. |
| exp06_pid_derivative | loop monitoring/tuning | active | PID beats PI except on delay-dominated loops; P3 failed; 0.5 threshold kept. |
| exp07_closed_loop_ident | loop monitoring/tuning | active | IV closed-loop fit with setpoint as instrument; v1 missed I1 and I3, the delay choice was the cause. |
| exp08_cascade | loop monitoring/tuning | active | Cascade targets C1 and C2 met; interaction is mild. |
| exp09_fuzzy_backtest | fuzzy/supervisor | active | Fuzzy supervisor backtest B1 met (0.805). |
| exp10_sacac_stiction | loop monitoring/tuning | closed | SACAC stiction index; closed. |
| exp11_fuzzy_retune | fuzzy/supervisor | active | v2 narrowed the rules; C1 met. |
| exp11_stiction_floor | loop monitoring/tuning | closed | Floor stays at 30; closed. |
| exp12_stiction_scoreboard | loop monitoring/tuning | closed | No candidate passes all gates; closed. Valve stroke test (exp25) is the stiction answer. |
| exp13_stiction_suspicion | loop monitoring/tuning | closed | Ranked 8 of 17 counted loops; closed. |
| exp14_stiction_classifier | loop monitoring/tuning | closed | Classifier missed C1 by 0.01; closed. |
| exp15_stiction_robust | loop monitoring/tuning | closed | Finalist C4a vs shipped; T2 and T4 missed; closed. |
| exp16_stiction_generalise | loop monitoring/tuning | closed | C7a not shipped; shipped module stays; closed. |
| exp17_history_tuning | loop monitoring/tuning | active | No real loop reached high or medium confidence from history; the bump test is the product answer. |
| exp18_kpi_triage | loop monitoring/tuning | active | Triage sensitivity passes on paper but is vacuous. |
| exp19_triage_no_knowledge | loop monitoring/tuning | active | "No oscillation" is unreliable below about 10 cycles; shipped ACF detector stays. |
| exp20_acf_short_records | loop monitoring/tuning | closed | No candidate meets F; shipped detector A stays; closed. |
| exp21_acf_peak_gate | loop monitoring/tuning | closed | Candidate G loses 4.3 points of L; not shipped; closed. |
| exp22_idle_index | loop monitoring/tuning | closed | Idle index not shipped; draft kept; closed. |
| exp23_acf_peak_gate_biased | loop monitoring/tuning | closed | Candidate J misses F on test; not shipped; closed. |
| exp24_acf_confirm_I | loop monitoring/tuning | closed | Candidate I misses L by 2 runs of 3600; not shipped; closed. |
| exp25_valve_stroke_test | loop monitoring/tuning | active | Valve stroke test V1, V2 and V3 pass in simulation; the stiction answer. |
| exp26_history_tuning_level | loop monitoring/tuning | active | H1 passes; level-loop history recommendations are safe in simulation. |
| exp27_supervisor_benefit | fuzzy/supervisor | active | E1 to E5 met on test seeds; advisory gating verified; benefit over the crisp rule shown. |
| exp28_integrating_step_test | loop monitoring/tuning | active | Round 1 misses I1 and I3; integrating-process tuning stays unvalidated until J1 passes. |
| exp29_anomaly_detection | anomaly | active | Round 3 B1 and B2 met; ships labelled "false alarm rate not validated on real data". |
| exp30_soft_sensor | virtual sensors | active | S1 and S2 met, S3 missed; affected case labelled "no better than last lab value". |
| exp31 | virtual sensors | validation case | Online analyser vs lab, plant-1 validation case: R1 passes both primary targets; R2 misses one (RMSE 1.074 vs limit 1.05) and passes the other; R3 misses both; bias correction is not a default for the failing target. |
| review_pack | foundations | active | Blind-review pack for the loop worklist (HANDOFF step 3). |
