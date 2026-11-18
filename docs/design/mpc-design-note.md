# MPC design note (Phase 7)

Status: design only. Nothing is implemented. Module: MPC (PRODUCT.md section 4.5). Builds on ADR 001
(language split), ADR 011 (write path), ADR 015 (APC core) and ADR 016 (setpoint handover).

The design is **blocked on ADR 011**: no MPC may write a setpoint until the Write Gateway safety suite passes
and the owner has run a supervised site test. The safety rules of ADR 011 stay in force.

## 1. Aim and position in the product

MPC is a constrained multivariable controller above the base PID layer. It proposes setpoints to base loops
that are in a remote-setpoint mode. It does not replace the PID and does not write controller outputs.

It runs as a controller on the APC core (ADR 015), next to the fuzzy supervisor. The operator console, the
variable model, the live variable status, loop readiness and the gateway are the same.

## 2. Prerequisites

The controller cannot start until all four items below exist. Each is a visible validation failure when missing,
never a silent fallback.

### 2.1 Identified MIMO model

A model with one dynamic path for every (MV, CV) and (DV, CV) pair. A single SISO model is not enough.

- Form: step-response coefficients per pair at the controller cycle, or a discrete state-space model with the
  same sample time. Each pair carries gain, dead time in samples, settling time and a fit metric.
- Source: step tests from the Steps view (`docs/design/step-analyzer.md`) plus a generalised driver-response
  tool. Tests must excite every MV, and must cover the DV range that the controller will meet.
- Quality gate: the existing gate in `loops/src/crosscut_loops/identification_quality.py` (free-run R2 and
  excitation events) applies per pair. A pair that fails the gate blocks the model.
- MIMO identification does not exist today. Only SISO FOPDT and IPDT fits exist (`identification.py`,
  `identification_oe.py`, `identification_ipdt.py`, `step_fit.py`).

### 2.2 Stored identification model artifact

The model is an artifact, not a hand-edited table. It is produced offline and read by the runtime.

- Bundle: an artifact directory with `manifest.json` per ADR 004 (`schemas/artifact-manifest.schema.json`).
  `artifact_type` is `ident_model` (a working name, fixed when the model schema is written); the payload holds
  the model data.
- Manifest fields: `creator` (tool and version), `inputs` (dataset hashes), `tags_signature`, `metrics`
  (per-pair fit), `valid_context` (operating modes, date window, tag list) and `signature`.
- The controller configuration in the site catalogue names the artifact id and its SHA-256. The runtime refuses
  to load a model whose hash does not match the manifest. A model is never edited in place; a retrain is a new
  artifact and a new version.
- The artifact reader verifies the payload on load, as `crosscut_artifacts.manifest.read_manifest` already does.

### 2.3 Controller binding in the catalogue

`schemas/site.schema.json` already has `controllers[]` with variables bound to loops (MV) or tags
(CV, DV, ICV), limits, priority and on/off. Two additions are needed:

- `controller.type` accepts `mpc` (the enum is `["fuzzy"]` today; the description already says `mpc` is added
  later).
- The controller names the model artifact and the horizon settings. The checks in `site_refs.py` (through
  `site_controllers.py`) already cover bindings, role counts and nested limits. MPC adds two rules: every model
  pair maps to a declared variable, and every MV loop has a remote-setpoint mode allowed by the write policy.

### 2.4 Quality variables (ICV)

A quality variable can only be a CV when a validated inferential model exists and is stored as an artifact.
That model does not exist.

- On four weeks of plant-1 data a process-only soft sensor had a negative blocked-CV R2 at every alignment.
  An analyser used as an input worked (CV R2 0.76 for Cu), but exp31 was not blind.
- The lab stamp meaning and the analyser delay are still open (ASSUMPTIONS A20). Without them the sample cannot
  be aligned with the process tags.
- Therefore an MPC with a quality CV cannot be commissioned now. The design keeps the ICV role and the model
  path, but validation fails visibly when the quality model is absent.
- A first MPC may control measured CVs only. That is a scope choice for the owner (section 7).

## 3. Controller structure

Two layers, one QP each, run in the same cycle. This is the standard industrial structure: a steady-state target
layer that decides where to go, and a dynamic layer that decides how to get there.

### 3.1 Steady-state target layer

Inputs: current CV measurements, operator CV targets, MV limits, DV values, and CV priorities.

- With no economic objective (Phase 8 is not built), the target is the operator CV target, or the nearest
  feasible point when the targets cannot all be met.
- Form: a small QP (or LP when the objective is linear) over steady-state MV targets `u_ss` and CV targets
  `y_ss`. Hard constraints are MV engineering and operator limits. CV limits are soft, with a slack variable
  per CV weighted by priority.
- Infeasibility is resolved by relaxing CV constraints in priority order. MV engineering limits are never
  relaxed. If no feasible point exists, the controller sheds to base control and says why.
- The target is rate-limited between cycles, so the dynamic layer never receives a step it cannot follow.

### 3.2 Dynamic move plan

Inputs: the model artifact, the current MV positions, the measured CVs, the steady-state targets and the
variable limits.

- Prediction: `y(k+j) = y_free(k+j) + sum_i G_i(j) * delta_u_i`, where `G_i` is the step-response matrix of
  MV `i`, `delta_u_i` is the planned move of that MV at each future step, and `y_free` is the free response
  with no further moves. All values are in engineering units.
- Output bias: at each cycle `d = y_measured - y_predicted_one_step`; `d` is added to every predicted CV
  sample. This removes steady model error and unmeasured load.
- Cost: `sum_j ||y(k+j) - y_target||^2 * Q + sum_j ||delta_u(k+j)||^2 * R`, over prediction horizon `Np` and
  move horizon `Nc`. `Q` follows CV priority; `R` penalises move size.
- Constraints: `move_max` and `rate_max` per MV from the variable model, operator limits on MVs and CVs, and a
  CV funnel. A funnel is the allowed band around the CV target; it starts wide and narrows over the horizon, so
  the CV returns to target at a controlled speed instead of as a step. The move plan must stay inside the
  gateway policy, so a proposal is not clamped or refused for size.
- Only the first move of the plan is proposed. The rest is discarded and the plan is recomputed next cycle
  (receding horizon).
- If the QP is infeasible, relax CV constraints in priority order first. If it is still infeasible, hold the
  last MV position and shed after a configured number of cycles. The exact rule is an owner decision.

### 3.3 State, handover and failure behaviour

- The host runs `off` / `standby` / `on` / `shed`, with `init` on entry to `on` (ADR 015). The implemented host
  also has `advisory` when the gateway cannot write; MPC uses that state unchanged.
- `initialise` reads the current MV positions, builds the bias and sets the first plan so that the first move is
  zero. Start is bumpless.
- A CV whose live status is `bad` is dropped from the CV set. A required MV that is unavailable, or a
  communication loss, sheds the controller. MPC holds an optional MV at its last value.
- Moves are `Move` objects from the controller host (`runtime/src/crosscut_runtime/controllers/protocol.py`).
  Each move becomes one gateway proposal. The controller never imports write code and holds no credentials.
- ADR 016 applies unchanged. The gateway does not take a loop to remote by default; it writes a setpoint only
  while the source node already shows the remote value. A proposal for a loop in local mode is refused with
  `not_remote`. The controller treats a refusal as "no move this cycle" and keeps the last target.
- On shed, release, kill or watchdog loss, the gateway returns the setpoint to the plant only while it owns it.
  The base PID then runs the loop.

## 4. Execution: C++ core and Python

ADR 001 puts the control runtime in C++20. Today the runtime and the controller host are Python, and the C++
core contains only the `Fopdt` smoke test with a pybind11 parity test.

- MPC prediction and the two QPs go into the C++ core as a pure function: model arrays, state, targets and
  limits in; move vector, target and status out. No file, network, clock or global state.
- The Python host calls it through pybind11, as `core/bindings/module.cpp` already does for `Fopdt`. A Python
  reference implementation stays beside it for the parity test required by ADR 001.
- Identification, artifact creation, model checks and reports stay in Python (`numpy`), offline.
- Determinism: fixed iteration cap and tolerance, fixed constraint and variable order, no wall-clock decision
  inside the solve. The same inputs must give the same moves. Solve time and iteration count are reported to
  the host for overrun monitoring.
- If the controller host later moves to C++, it uses the same core code. The QP solver choice (own active-set
  code or a permissively licensed library) is open; a library adds a licence and packaging decision.

## 5. Out of scope

- Nonlinear MPC, gain scheduling and online model adaptation.
- The economic layer and real-time optimisation (Phase 8).
- The quality soft sensor itself (Phase 4.2); MPC consumes a model, it does not build one.
- Valve tests, stiction diagnosis and PID tuning (Phase 3).
- Writes to controller outputs, valve or drive commands, or the loop mode. Taking a loop to remote is a DCS
  operator action under ADR 016.
- Multi-unit coordination, sub-second cycles and controller cycles longer than the process dead time.
- Any claim that a simulator result transfers to a plant (PRODUCT.md section 8).

## 6. Tests

- L1: C++ and Python parity on known linear plants, including an infeasible QP and a saturated MV.
- L5 against RougherSim: step tests identify the model, MPC holds the CVs inside limits, a required MV going
  unavailable sheds the controller, a refused `not_remote` proposal leaves the last target, a restart returns
  in `standby`, and the operator console switches the controller on and off.
- No plant claim. A pilot is Phase 7 work under the owner's agreement.

## 7. Open owner decisions

| # | Decision | Blocks |
|---|---|---|
| 1 | Whether the first customer needs MPC at all (also in `docs/OWNER_TASKS.md`) | the whole phase |
| 2 | The first unit and its CV, MV and DV list | model identification |
| 3 | The quality variable, and whether lab or analyser data with stamp and delay will be supplied | any quality CV (ICV) |
| 4 | Whether v1 may control measured CVs only, with quality left to the operator | scope of the first controller |
| 5 | Who runs the step tests and owns model refresh, and how often a model is re-identified | model lifecycle |
| 6 | Whether MPC setpoint writes are allowed in `supervised`, and who may enable that mode | Phase 7 exit |
| 7 | Default horizons, cycle period and the accepted overrun and shed behaviour | controller configuration |
| 8 | Infeasible plan: hold the last MV position or shed, and after how many cycles | safety behaviour |
| 9 | QP solver: own code or a third-party library, and its licence | C++ core delivery |
