# exp43: frozen-protocol MPC versus tuned PID and fuzzy on the RougherSim grinding bed (#186)

Status: protocol frozen 2026-11-27 by the commit that adds this file; held-out seeds not run in that
commit. Module: MPC (Phase 7.5, `docs/design/mpc-design-note.md` sections 8 and 8.1). A change after
the held-out run creates `exp43_v2`; only definition-preserving bug fixes are allowed in v1 and are
reported.

## Hypothesis

On the RougherSim grinding bed, an MPC built from a Crosscut-identified model beats a SIMC-tuned
PID pair and the fixed fuzzy rule base, under the same MV ranges, move limits and CV limits, on
three criteria: tracking error (IAE), constraint violations and MV travel (no more than 1.25x the
reference). A miss is reported as a miss. Stage 7.5 asks for "CV variance, constraint violations,
distance to the active constraint"; variance is covered by the mean-square error (reported) and
IAE (decisive), the distance to the constraint is reported without a pass line (a larger margin
is not better in itself when the target sits at the constraint).

## Plant

RougherSim `scenarios/grinding/flowsheet.json` at commit
`c09b17a883a90611dbb5eceb652628c4402d9a91` (origin/main 2026-11-27, includes #22 grinding bed,
#23/#29 gain-matrix truth, #24 step-test scenarios), stepped in process (`Plant.step`, 5 s). The
runner refuses any other commit (`ROUGHERSIM_DIR`, default the sibling checkout). The hardness
disturbance `mill_hardness` is an OU process with sigma 0.02 (the bed ships with sigma 0) so each
seed has a different realisation; instrument noise is seeded per seed. After a 3600 s warm-up the
settled plant is deep-copied, so all three controllers start from the same state and see the same
noise and hardness streams (paired design).

## Choice of the MIMO pair set (done before freezing)

Ground truth: `step_test.json` of `rs.grinding.step_test_sequential.v1` (seed 100024), gains per
SP unit. Only self-regulating pairs have a static gain; WIC101/SIC201 to LIT201, WIC101 and
SIC201 to JT101, and SIC201 to DIT202 are integrating in the truth.

Condition number: columns scaled by the step-test amplitude (WIC101 8, FIC102 4, SIC201 2), rows
to unit norm. RGA is scale free.

| Set (MVs -> CVs) | cond | RGA diagonal | Verdict |
|---|---|---|---|
| rejected: WIC101, FIC102 -> PDT204, DIT202 (the L5 pairs of #184) | 1818 | 99.8 (off-diagonal -98.8) | rejected: gains 0.0195/0.0043 and 0.0563/0.0125 are proportional (ratio 4.54 and 4.50) |
| chosen: FIC102, SIC201 -> JT101 (mill power, MW), PDT204 (cyclone pressure, kPa) | 1.002 (truth, integrating SIC201->JT101 counted as zero); 7.4 (identified, SIC201->JT101 fitted as a lag, see below) | 1.0 / 1.0 (identity) | chosen |

The chosen set is well conditioned because each CV is dominated by a different MV: FIC102
(mill water) moves power (-28.75 kW per m3/h, tau 626 s), SIC201 (pump speed) moves cyclone
pressure (+4.97 kPa per percent, tau 6 s in truth). Other self-regulating sets were not usable:
WIC101 -> DIT202 failed the Crosscut identification gate in development (free-run R2 below 0.6,
the response is not first order), so DIT202 is not a CV here. The price of a well-conditioned set
is a weak steady-state interaction (RGA close to identity): do not expect an MPC advantage from
decoupling; the realistic sources are the measured hardness DV (feedforward) and the CV limit.
JT101 is expressed in MW (not kW) in every controller: in kW the MPC QP was so badly scaled that the
solver hit its iteration cap and the engine shed after a few cycles (found on development seeds).

## Identification (same for all controllers)

The #24 sequential scenario is replayed unchanged (seed 100024, sigma 0, same SP schedule), then
one measured-disturbance pulse is appended: hardness +0.05 at 15600 s, back to 0 at 16500 s
(the gate needs two input moves). Sampling is the controller cycle, 30 s. All six (CV, input) pairs
(inputs FIC102, SIC201, HIT101) are fitted with `crosscut_mpc.identification.identify_mimo` on the
windows of `frozen_config.json`. A pair is enabled when it passes the Crosscut gate and
|K| x test amplitude >= 4 x CV noise sd; disabled pairs have zero gain. The pairs FIC102 -> JT101 and
SIC201 -> PDT204 are required; if one is not enabled the run stops (`IdentificationRejected`) and
that is the result. One consequence on the development run: SIC201 -> JT101 (an integrator in the
truth) passes the gate as a long lag (K 0.26 MW per percent, tau 1220 s). The MPC therefore uses
pump speed as a second handle on power; this plant-model mismatch is part of what is tested.

## Controllers

All act on the SP of the inner FIC102 and SIC201 loops every 30 s, through the existing runtime
code where it exists, with the same limits: MV operator range (FIC102 28 to 56 m3/h, move_max 2
per cycle; SIC201 22 to 32 percent, move_max 0.5 per cycle), CV operator limits (JT101 7.0 to 8.8
MW, PDT204 65 to 80 kPa), `crosscut_runtime.controllers.mpc_limits.clamp_move` for the step window.

- **PID**: two velocity-form PI loops, FIC102 on JT101 and SIC201 on PDT204, SIMC
  (`crosscut_loops.tuning_rules.simc_pi`) from the identified diagonal pair with
  tau_c = `lambda_from_robustness(model, 0.5)`; sign of the gain kept. No feedforward.
- **fuzzy**: the runtime `FuzzyController` on a fixed Mamdani rule base (5 terms per error, 5 delta
  terms per MV, one rule per term): power above target raises FIC102, pressure above target lowers
  SIC201. It sees the CV errors only (no hardness rule, no integral action beyond the incremental
  structure). The rule base is generated by `fuzzy_document()` and frozen with the code.
- **MPC**: the runtime `MpcController` (#184) on the identified model with the hardness DV,
  prediction horizon 60 and move horizon 8 samples (30 s), move suppression 0.1, CV priorities
  JT101 1 and PDT204 2 (the limit relaxes PDT204 first), CV targets as below.

Development fixed the unit of JT101 (MW), the move suppression (1.0 tried; 0.1 chosen on
development seeds 200001 and 200002 from 1.0, 0.3, 0.1, 0.03 with horizons 60/8 and 40/6) and the
DV pulse; nothing was tuned on the held-out seeds, which have not been run.

## Scenario (7200 s after the warm-up, same for every seed and controller)

Targets: JT101 8.5 MW (the nominal operating point sits near 8.1 to 8.3 MW, so the first 900 s
include a move to the target), PDT204 75 kPa. Events: PDT204 target 78 kPa at 900 s; hardness
+0.08 at 2400 s (open-loop power about +0.7 MW, above the 8.8 MW limit); hardness back to 0 at
4800 s; PDT204 target 75 kPa at 5400 s. Limit violations and errors are evaluated on the
noise-free truth values.

## KPIs (per seed and controller; CV errors divided by the CV operator span)

- `iae`: sum over both CVs of integral |CV - target| / span (seconds); `mse`: mean-square error.
- `violation`: sum of integral of the excursion outside the operator limits / span (seconds);
  `violation_time_s`: time outside the limits.
- `travel`: sum of |dSP| / MV range, both MVs.
- `margin_mw`: mean distance of JT101 below its upper limit during the high-hardness window.
- Economic value: the engine has no economic objective (targets only), so it is not evaluated.

## Seeds

Development (used to choose the settings above): 200001, 200002. Held-out (run once, after this
commit): 300001 to 300008. Seeds select the instrument noise and the hardness OU realisation; the
identification uses its scenario seed 100024 and is identical for all seeds.

## Pass criteria (against PID and against fuzzy, separately; all must hold for "advantage")

- **P1 IAE**: median over held-out seeds of paired ratio IAE(MPC)/IAE(other) <= 0.90, and MPC has
  the lower IAE on at least 75 percent of the seeds.
- **P2 violations**: median MPC `violation` <= median of the other + 0.001 (a tie at zero passes).
- **P3 travel**: median paired ratio of `travel` <= 1.25.

Any other outcome is reported as "no demonstrated advantage" with the failed criteria named.

## Development observations (not evidence; seeds 200001, 200002, frozen settings)

PID IAE 771 to 801, violation 84 to 96, travel 10.6 to 11.4; fuzzy IAE 1231 to 1407, violation
522 to 672, travel 2.6 to 2.9; MPC IAE 1156 to 1226, violation 60 to 63, travel 10.7 to 11.6. On
these seeds MPC cuts the violation by about a third against PID but tracks worse (IAE ratio about
1.4): P1 is expected to fail. This is stated here so that the held-out verdict is read against it.

## Files and run

`frozen_config.json` (all numbers above), `exp43.py` (runner), `test_exp43.py` (synthetic unit
tests, no simulator). Run:
`ROUGHERSIM_DIR=<checkout at the pinned commit> python experiments/exp43_mpc_vs_pid/exp43.py --seeds held_out --out <dir>`
(needs the Crosscut packages and RougherSim dependencies on `PYTHONPATH`; the Python engine is
used, the C++ core is not required).
