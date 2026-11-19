# DML operating-range note (Phase 8)

Status: design accepted 2026-11-19 as stage 8.3 of Phase 8 (PRODUCT.md section 4.6). Nothing is implemented
yet. Module: ML operating-range recommendation.

DML here means double/debiased machine learning: estimate a low-dimensional causal effect while flexible
learners adjust for observed confounders. The method is described in Chernozhukov, Chetverikov, Demirer,
Duflo, Hansen, Newey and Robins (2018), "Double/debiased machine learning for treatment and structural
parameters", The Econometrics Journal 21(1), C1-C68.

The note states what the method could answer, what it needs from the owner, how it is checked against
RougherSim ground truth, and where the method stops.

## 1. Question

A process engineer asks: "If I move this operating variable, what happens to quality or throughput, and which
range should I run in?"

- Treatment `T`: one operating variable that operators actually move, for example mill feed, cyclone pressure,
  flotation air or pump speed.
- Outcome `Y`: one measured result, for example P80, grade, recovery or solids flow.
- Covariates `X`: what was known before the move, for example ore type and hardness, feed rate, equipment
  state and operating mode.
- Confounders: variables that change both `T` and `Y`. Ore hardness is the obvious one. Operators also move
  setpoints in response to what they see (ASSUMPTIONS A3, A4 and A15), so `T` is not exogenous.

Two products must be kept apart:

1. An **effect estimate**: the change in `Y` for a change in `T`, with a confidence interval, inside the
   observed range.
2. An **operating-range recommendation**: the value of `T` that gives the best stated objective inside the
   allowed limits. This needs the effect estimate plus an objective, limits and a decision rule.

The second does not follow from the first. A positive effect does not say where to stop, and a peak in the
observed data may sit at the edge of the data.

## 2. Blockers and owner decisions

### Objective (decided 2026-11-17, #35: per-site configuration entered by the user)

- What is maximised or minimised: grade, recovery, throughput, energy per tonne, or money.
- The unit and the value per unit.
- The allowed operating limits and the constraints that must never be violated.
- The time horizon over which the objective counts (per shift, per week, steady state).

Without this there is no "best range". The same data can recommend opposite moves for two objectives.

### Data (decided 2026-11-17: owner-site data excluded; RougherSim ground truth and public datasets with a licence check and a row in `docs/PROVENANCE.md`)

- Real historian data: tags, units, ranges, quality codes, missing-value codes and operating modes.
- Lab or analyser results with the stamp meaning, composite window and analyser delay (ASSUMPTIONS A20).
- Enough variation in `T` that is not explained by `X`. If operators only move `T` when ore changes, the
  effect and the ore effect cannot be separated.
- Permission to use the data. Plant data stays outside the repository (PRODUCT.md section 8).

Per site, the user enters the objective items above in the GUI; without them the product shows effect estimates only, never a recommended range.

### Treatment, outcome and confounders (decided 2026-11-19)

The user selects `T`, `Y` and the confounders `X` from the site catalogue in a GUI question builder before any
analysis. The engine may propose candidates, but the choice is a process decision, not a statistical one.

## 3. Causal assumptions

The estimate is only as good as these assumptions. Each one must be written in the protocol and checked where
possible.

1. **Consistency.** The recorded value of `T` is the value the plant actually ran at, after compression,
   rounding and dead time (ASSUMPTIONS A21, A22).
2. **Temporal order.** `X` is measured before `T`, and `T` before `Y`. The dead time and the lab composite
   window are respected. A sample stamp is not an instant (A20).
3. **No interference.** One unit's treatment does not change another unit's outcome. Coupled units, such as
   cells in series or a mill and its sump, break this unless they are modelled as one unit.
4. **Positivity (overlap).** For every `X` there is a real chance of seeing both low and high `T`. At the
   operating limits this fails: the data say nothing about a move the plant never makes.
5. **Unconfoundedness.** Given `X`, `T` is as good as randomly assigned. This cannot be tested from the data.
   It is a judgement about the process, and it is the main risk.
6. **Nuisance quality.** The ML models for `E[Y|X,T]` and `P(T|X)` must converge fast enough that their error
   does not dominate the effect. Cross-fitting removes own-observation bias but not a badly specified model.
7. **Dependence.** Process data are autocorrelated. Cross-fitting must use time blocks, not random rows, or
   the confidence interval is too narrow.

Unmeasured confounding remains. Examples are ore mineralogy that is not in the tag list, operator intent, and
maintenance state. The report must include a sensitivity statement: how strong an unmeasured confounder would
have to be to remove the effect. No such confounder can be ruled out from the data alone.

## 4. Validation against RougherSim ground truth

A causal estimate on plant data has no counterfactual. The only place where the true effect is known is a
generator: RougherSim, or a purpose-built synthetic plant.

RougherSim exposes a ground-truth channel that tests may read (PRODUCT.md section 6). The protocol is frozen
before the run (TESTING_STRATEGY.md), including scenario, seed and pass criterion. Seeds are spent once.

| Case | Generator truth | What it checks |
|---|---|---|
| Known linear effect, no confounding | effect and slope set by hand | the estimator recovers the true sign and size inside the interval |
| Confounded effect, confounder in `X` | ore hardness drives both `T` and `Y` | adjustment removes the bias |
| Confounded effect, confounder hidden | the same, but the confounder is not given to the estimator | the estimate is biased and the interval misses the truth; this is the expected failure |
| Placebo treatment | `T` has no effect by construction | the estimate is near zero and the interval covers zero |
| Non-linear response | a known peak inside the range | the estimator finds the shape, and refuses outside overlap |
| Operating-mode change | the effect differs by mode | a single pooled estimate is shown to be wrong; per-mode estimates are needed |
| Dead time and sample window | a known delay between `T` and `Y` | alignment recovers the delay; a wrong stamp shifts the estimate |

What this proves: the estimator works on data that obey the assumptions, and it fails visibly when a
confounder is removed. What it does not prove: that the plant's confounders are all in `X`. The simulator
confounder is ours, so a simulator pass is not a plant claim.

## 5. Limits of the method

- **Causal claims need assumptions, not data.** DML cannot prove that no confounder exists. It reports an
  effect conditional on unconfoundedness, positivity and the rest.
- **Extrapolation at the edge.** The recommended range often sits at a constraint, where overlap is thinnest.
  The method must refuse to recommend outside the observed treatment range.
- **Local, conditional effects.** The estimate is for the observed period, ore and mode. It may not transfer to
  another ore body, another campaign or after an equipment change.
- **Non-stationarity.** Ore hardness, liner wear and feed changes move the response over weeks. A single
  average effect can hide a trend; time-varying effects need more data and a stronger design.
- **Measurement error.** Sparse lab samples, composite windows and analyser latency add noise to `Y`. Noise in
  `T` or `X` biases the effect, not only widens the interval.
- **Data traps.** PI compression, sentinels and linear ramps (A21-A23) can create or hide variation that the
  estimator treats as real.
- **Small samples.** Plant campaigns are short and autocorrelated. Wide intervals and weak placebo tests are
  the honest result, not a failure to be tuned away.
- **The recommendation is advice.** It is not a controller and not a write. Any move goes through the normal
  operator decision and, if it becomes a setpoint proposal, the Write Gateway.
- **Own-generator risk.** A method developed and tuned only on our simulator can fit our generator. Evidence
  needs at least one plant data set that was not used during development, and the result must be reported with
  its assumptions.

## 6. Work items before coding

1. Objective, limits and value per unit: per-site configuration in the GUI (decided).
2. Data: RougherSim ground truth and public datasets (decided); a site supplies its own historian data.
3. `T`, `Y` and `X`: chosen by the user in the question builder (decided).
4. Write the protocol: assumptions, estimator, cross-fitting blocks, placebo and sensitivity tests, pass
   criteria. Freeze it before the first run.
5. Build the RougherSim ground-truth cases in section 4 and run them once on unused seeds.
6. Only then add a report view. No GUI work before the estimator passes its frozen protocol.

## 7. Place in Phase 8 (2026-11-19)

| Stage | Scope | Exit criterion |
|---|---|---|
| 8.1 Economic layer | Objective in the MPC steady-state target (value per CV unit, MV cost, limits); GUI objective editor and benefit report | On RougherSim the economic MPC yields higher value than setpoint-tracking MPC without constraint violations |
| 8.2 Model registry | Shared by soft sensors, anomaly models and MPC models; versions from Phase PL; drift and model-mismatch monitoring; retrain recommendation; GUI "Models" view | A model degradation on RougherSim (ore change) is flagged within the lead time of a frozen protocol |
| 8.3 Operating-range recommendation (this note) | First a descriptive best-operating envelope per operating mode (conditional quantiles), then DML with blocked cross-fitting, overlap map, sensitivity statement and refusal outside the observed range | The seven RougherSim cases of section 4, including the expected failure with a hidden confounder |
| 8.4 RTO | Steady-state flowsheet optimisation, e.g. on a RougherSim surrogate | Later; out of v1 |

Issues: #187-#191 (epic #164).
