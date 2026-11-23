# Crosscut Process Suite — Product definition

This document is the single product definition of the Crosscut Process Suite. It replaces `docs/PROJECT_DESIGN.md`, which is kept only as a historical record. The ADRs in `docs/adr/` override this document where they conflict. Date: 2026-10-27; the "current state" statements ("Exists today", "Ships today") were brought in line with origin/main on 2026-11-18.

**Implemented is not validated.** Every state statement below says what is built. What is validated is stated separately and is less: results on simulators are not plant claims, and the public-data benchmarks of 2026-11-18 are mixed (section 8).

## 1. Product definition

Crosscut is an on-prem server with a browser console in which a process engineer configures the system **without programming** (the *no-code* principle): they connect a historian or DCS of any vendor, analyse and model the process (loops, virtual sensors, anomalies, rules, MPC, optimisation), run the models online, and change setpoints in the control system through one safe **Write Gateway**, in modes `advisory` → `confirm` → `supervised`.

| User | Role |
|---|---|
| Process engineer | Connects sources, builds the project catalogue, designs and deploys models. Owns no-code configuration. |
| Operator | Works the console, accepts or rejects proposed writes in `confirm` mode. |
| Controls engineer | Owns the write policy, the gateway configuration and the safety settings. Supervises anything that touches a controller. |

Owner decision 2026-11-17: Crosscut is a framework, not a setup for one plant. Plant data from the owner's site is not used for development or validation. Validation uses public datasets; site facts (tunings, sample metadata, vendor conventions, economic values) are per-site configuration entered by the user. Check the licence before use and add a row to `docs/PROVENANCE.md`; download to a scratch folder outside the repository; never commit or redistribute data. CC BY-SA and unlicensed datasets are used locally only; no derived data is published.

## 2. Owner decisions of 2026-10-27

1. Writes are a product capability, implemented through one Write Gateway. `confirm` and `supervised` modes are in scope for v1.
2. First complete product: loop monitoring plus PID tuning, from data intake to online work with writes.
3. Connector order: OPC UA → PI → SQL/ODBC → the rest.
4. Deployment: on-prem server plus browser. No cloud.
5. A DCS simulator imitating ABB 800xA is a separate project (Phase 1a).

Earlier documents recorded a "no writes to a plant" position (PROJECT_DESIGN §1, ADR 010, ADR 011 preamble). That position is superseded by ADR 012. The safety rules of ADR 011 remain in force.

## 3. Architecture layers

| Layer | Responsibility | Exists today | Gap |
|---|---|---|---|
| **Connect** | Read history and live values, browse metadata; write only through the gateway | One read connector interface (browse, metadata, history, live); CSV wide/long history and imports, SQLite and any DB-API/ODBC connection (pyodbc is not a dependency), SQL historian profiles (Aspen IP.21, Honeywell PHD, AVEVA/Wonderware, Siemens WinCC) as data, PI Web API, OPC UA polling and subscription, a Parquet collector. Tested on recorded fixtures and simulators, not on real sources | No AF SDK, OPC DA/HDA |
| **Project catalogue** | Sources, tags, units, ranges, missing codes, time zone, loops (PV/SP/OUT/mode/PID parameters in vendor form), lab definitions; edited in the GUI | Built in part: one schema-validated site file `_site/site.json` (`schemas/site.schema.json`) with sources, units, tags, signals, equipment hierarchy, loops, labs, operating modes and controllers; catalogue editor in the GUI (direct editor and mapping wizard with role suggestion); catalogue loops drive the Loops, Anomalies and Soft sensor views; one site-settings function serves all importers | Versioning with diff, bulk CSV edit, loop templates, vendor profiles as data. Operating modes are stored and used for reference checks, but KPIs, anomaly limits and strategies do not yet work per mode |
| **Engines** | Offline design mode and online run mode for each module | Loops, fuzzy, supervisor, anomaly, soft sensor: offline, on demand, over a stored window; loop KPI, anomaly scan and tuning review also run online as runtime jobs; the fuzzy supervisor runs online as a controller (APC core). Schema-generated configuration forms (nested objects and arrays; raw JSON only as an advanced fallback for oneOf/anyOf schemas) | No online soft-sensor job (the backup mode is in the engine, not in the runtime). Not every configuration has a dedicated editor |
| **APC core** (section 3.2, Phase 2.5) | Shared variable model, live variable status, loop readiness as MV handle, controller host with a state machine, operator console | Built (ADR 015, Phase 2.5): variable model with nested limits in the catalogue, live variable status (including anomaly findings), MV readiness of loops, controller host, fuzzy controller, operator console (Controllers view) | Only one controller type (fuzzy). Validated in simulation only (L5 C rows against RougherSim); no plant claim |
| **Runtime** | On-prem service (Windows service or systemd) runs deployed jobs cyclically: loop KPI, anomaly scan, soft-sensor estimate, fuzzy advice. Status, error log, start/stop from the GUI | Scheduler with per-job period, jobs `loop_kpi`, `anomaly_scan`, `tuning_review` and `controller`, atomic state files, systemd unit, Runtime view. Controller host with overrun monitoring and liveness beats to the gateway | No soft-sensor job |
| **Write Gateway** | Separate process. Writes proposals only. Policy as data, read-back, watchdog, operator priority, kill switch, audit | Implemented (ADR 012-017): five modes, OPC UA adapter, policy clamps, read-back (also delayed), operator priority, latched kill switch, keyed audit chain, local users and roles with login, tuning parameter sets with durable write intents, setpoint handover (ADR 016), bounded OUT tests in MAN (ADR 017), one DCS heartbeat sent by the gateway, liveness monitoring of the runtime and of each controller. Tested against simulators only | No explicit bumpless initialisation. Real-DCS conformance is not established |
| **Web console** | Browser UI: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import, Steps | React + TypeScript frontend, e2e suite green. Views: Trends, Loops (detail, tuning, benefit, valve), Fuzzy, Advisor, Anomalies, Soft sensor, Steps, Import, Catalogue, Onboarding, Runtime, Controllers, Gateway (proposal queue, policy panel), Tuning, Users; login, forced password change, roles; English, Polish, Spanish | Some module configurations have no dedicated editor beyond the generated form; no strategy canvas |

### 3.1 Project catalogue

**Purpose.** The single description of the plant that every module reads. Presets (4.2), asset templates (4.3), strategies (4.4) and loop templates (4.1) bind to roles, and the catalogue is where roles meet real tags. Nothing plant-specific lives in `*/src`; it lives here, as data validated by `schemas/`.

**Contents.**

| Element | What it holds |
|---|---|
| **Sources** | Connector type and address, polling and history settings, time zone, clock offset. Credentials are kept in the operating-system secret store, never in the catalogue file |
| **Tags** | Source address, description, engineering unit, physical range and engineering limits, data type, sampling and historian compression, missing-value codes, mapping of source quality to good / uncertain / bad |
| **Equipment hierarchy** | Site → area → unit → equipment (ISA-95 levels), with each tag attached to its equipment. Per equipment: criticality (consequence of failure) and the bound asset template (4.3) |
| **Loops** | PV, SP, OUT and mode tags; loop type (4.1); action direction; output limits; cascade, ratio and feedforward links; PID parameters in the vendor's form and the vendor profile that converts them |
| **Labs and analysers** | Sample point, measured variable, stamp meaning (start, end, or middle plus offset), composite window, analyser latency, missing codes, validity range |
| **Operating modes** | Named modes defined as conditions on tags (stopped, start-up, normal, high throughput, ore change, cleaning), per area or equipment. Shared by loop KPIs (4.1), virtual sensors (4.2), anomaly limits (4.3) and strategy states (4.4) |
| **Units** | Unit of every tag and the conversions between units used by presets and templates |

**Vendor profiles.** PID conventions differ by vendor: gain or proportional band, integral time in seconds, minutes or repeats per minute, ideal, parallel or series algorithm, derivative filter. A vendor profile (data, one file per vendor: ABB first, then Siemens, then others) converts between the vendor form and one internal canonical form. Every tuning result and every PID write goes through this conversion and shows both forms to the engineer.

**Building it in the GUI.**

1. Browse the source and pick tags; metadata the source exposes (OPC UA engineering units and range, descriptions, PI point attributes) is imported automatically.
2. The engine proposes, and the engineer accepts or edits: PV/SP/OUT/mode groups detected from the vendor profile's naming patterns, missing-value codes found in the data, equipment grouping from tag names, operating-mode conditions from history.
3. A readiness report (the existing historian-readiness checks) lists what blocks each module: missing range, unknown unit, unmapped quality, too short history.
4. Bulk edit through CSV export and import, validated on import, because engineers maintain large tag lists in spreadsheets.
5. Every change is a version with a diff. A module configuration that refers to a removed or changed tag fails validation visibly; it never runs on a wrong tag.

**Ships today.** `schemas/site.schema.json`: one site file with sources, units, tags, signals, equipment hierarchy, loops (with their knowledge), labs, operating modes, controllers and readiness settings; no plant-specific defaults. GUI: catalogue editor (direct editor and mapping wizard with role suggestion), sources panel, onboarding; a remap updates untouched generated anomaly and soft-sensor configs and reports a conflict otherwise. `project.json` is kept only for loops outside the catalogue. **Not built:** versioning with diff, bulk CSV edit with validation, automatic proposals of modes and equipment, per-mode use of the operating modes by the modules, loop templates. **Planned debt:** vendor PID profiles are still a code dict (`VENDOR_FORMS` in `loops/src/crosscut_loops/vendor_forms.py`: ABB PidCC and Siemens PID Compact), not declarative data files; moving them to data is planned.

**Phase.** 1.

### 3.2 APC core

**Purpose.** Crosscut is an APC framework (owner decision 2026-11-10): every controller type (fuzzy supervisor in Phase 2.5, MPC in Phase 7, the economic layer in Phase 8) runs on one shared core instead of keeping its own notion of variables, limits and state. Details and the decision record: ADR 015.

| Element | What it is |
|---|---|
| **Variable model** | In the catalogue: a tag is bound to a controller as MV, CV, DV or inferential CV (a virtual sensor). Per variable: engineering limits, operator limits, validity limits, move and rate limits, priority, operator on/off |
| **Live variable status** | Per cycle: one time-aligned snapshot of the inputs; status good / uncertain / bad from source quality, staleness, communication loss, anomaly findings (4.3) and virtual-sensor validity (4.2) |
| **Loop readiness** | Per base loop: can it serve as an MV handle now (mode allows remote setpoint, output not saturated, valve health, gateway not in hold-off) |
| **Controller host** | In the runtime: fixed cycle, overrun monitoring, state machine `off` / `standby` / `on` / `shed` with initialisation, restart-safe state, heartbeat. A bad CV is dropped; an unavailable MV or lost comms sheds the controller to base control |
| **Operator console** | Controller and variable on/off, operator limits, status, explanation of the last move |

Writes stay gateway-only (section 5): a controller produces proposals; the gateway's policy, mode ladder and audit apply unchanged.

**Built (ADR 015, owner decisions 2026-11-18).** Controller host in the runtime with the state machine `off` / `standby` / `on` / `shed`; cycle `cycle_s` 10-300 s, default 30 s, which is also the job period; an overrun is a start later than 1.1 x the period; `max_overruns` in a row shed the controller, default 5. An operator (permission `ctl.operate`) may switch a controller `on`; gateway target mode `supervised` is enough, `confirm` is not required, and in `off`, `advisory` or `dry_run` the gateway refuses the writes. Exactly one heartbeat goes to the DCS, sent by the gateway; the runtime process and each controller send liveness beats to the gateway through the signed mailbox, and the gateway releases the targets of a controller (or of all controllers, if the runtime is lost) after `liveness_cycles` x `cycle_s` of silence (default 3 cycles) and audits the loss; the console shows beat age and an alarm. Variable status takes anomaly findings; the fuzzy supervisor is the first controller. **Not established:** closed-loop behaviour against a real DCS; only simulator tests exist.

**Phase.** 2.5.

## 4. Modules

### 4.1 Loop monitoring and PID tuning — first release

**Purpose.** Tell the engineer which loops are healthy, which need attention, why, and what to do next, then carry the fix through to the controller safely: detection → diagnosis → test → tuning → write after confirmation → KPI check → one-click rollback.

**Loop templates.** Each loop in the catalogue has a type, and each type has a template (data under `loops/templates/`, validated by a schema, fully editable): expected dynamics range, KPI thresholds, diagnosis rules that apply, preferred tuning rule and closed-loop target, allowed test types and safe default step size.

| Loop type | Typical tuning target | Notes |
|---|---|---|
| Flow | Fast and tight; closed-loop time constant near the dead time | Noisy PV; valve problems show here first |
| Pressure (liquid or gas) | Fast (liquid) or moderate (gas) | Gas pressure is often integrating |
| Level, tight | Hold the level close to setpoint | Integrating process |
| Level, averaging | Use the tank to absorb flow changes; tuning from the allowed level swing | Integrating; tight tuning here is a fault, not a feature |
| Temperature | Robust, slow; derivative where justified | Long lags, often a cascade outer loop |
| Density and consistency | Moderate | Measurement noise and slurry effects |
| Composition or analyser | Slow, robust; sample time and analyser delay respected | Often fed by a virtual sensor (4.2) |
| Speed and drive | Fast | Usually inner loop of a cascade |
| Cascade inner / outer, ratio, feedforward | Inner tuned first, outer on the identified closed inner loop | Templates hold the link and the tuning order |

**Monitoring KPIs** (computed online per loop and per operating mode; excluded while the equipment is stopped):

- service factor: share of time in the intended mode (auto, cascade);
- output saturation share and time at limits;
- control error: standard deviation and integrated absolute error normalised by range;
- oscillation index (ACF test) and plant-wide oscillation clusters (loops oscillating at a common period);
- valve travel per hour, reversals, stiction suspicion, quantisation;
- noise level of the PV;
- setpoint response where setpoint changes exist (overshoot, settling time);
- later: a minimum-variance performance index once its assumptions are checked on real data.

**Worklist and diagnosis.** One finding per loop and problem, ranked by severity × equipment criticality × estimated benefit. Each finding names its probable cause class and the next action. The diagnosis order is fixed, because tuning around another fault makes things worse:

1. **Instrument:** frozen, noisy or drifting PV (shared with 4.3).
2. **Valve:** stiction, deadband, saturation, wrong sizing → valve test, maintenance, not tuning.
3. **External cause:** the loop oscillates at the same period as others → find the source loop in the cluster, do not retune this one.
4. **Design or mode:** loop kept in manual, wrong action direction, missing cascade or feedforward.
5. **Tuning:** only when 1–4 are ruled out.

Every finding gets an outcome from the user (fixed, not a problem, deferred, maintenance raised), as in 4.3, so the worklist learns which findings are useful.

**Tuning path.**

1. **Model.** From history (closed-loop identification, FOPDT or integrating) or from a step test planned by the assistant. A model-quality gate refuses tuning when data is insufficient (SP-only steps, clipping, too small output moves, unknown units) and says what data is needed. A refusal is a valid result.
2. **Rule and target.** Rule from the template (SIMC, AMIGO, lambda); the engineer chooses the speed/robustness trade-off on a slider with the robustness margin shown.
3. **Preview.** Predicted response with current and proposed parameters, side by side, on the identified model; parameters shown in canonical and vendor form (catalogue vendor profile).
4. **Write.** Proposal to the Write Gateway, `confirm` only for PID parameters (section 5). Operator and engineer see the reason, the old and new values and the rollback point.
5. **Check.** After a settle period the KPIs are compared before and after, per operating mode, over a window set in the template.
6. **Rollback.** Previous parameters restored in one click, and proposed automatically if the KPIs worsen.

**Valves.** Guided stroke test, bounded OUT tests in MAN through the Write Gateway (ADR 017, owner decision 2026-11-17), stiction quantification, valve-health trend shared with the valve asset template (4.3).

**Benefit and reports.** Benefit estimate: variance reduction → possible setpoint move toward a limit → value per year, using the value per unit of PV entered by the user (per-site configuration, decision 2026-11-17). Shift and weekly loop report: what changed, what was fixed, what still waits.

**Ships today.** Worklist with findings (manual, saturated, flatline, oscillating); ACF oscillation test and oscillation clusters; valve health KPIs, stiction suspicion and guided stroke test; closed-loop and step identification (FOPDT, integrating experimental) with a quality gate; tuning report (SIMC/AMIGO, cascade planning); benefit estimate; Steps view. Loop KPIs also run online as a runtime job. PID parameter write in `confirm` through the gateway, before/after KPI review and rollback exist against simulators (ADR 014); the step-test assistant proposes bounded OUT tests in MAN, `confirm` only (ADR 017); MV readiness of a loop is available to controllers (section 3.2). No loop templates, no per-mode KPIs, no cause ordering in the worklist, no outcomes; vendor PID forms are code (`vendor_forms.py`), not data - planned debt: declarative vendor profiles.

**Validated so far.** Public-data benchmarks of 2026-11-18: exp33 two-tank (5 targets met, 1 missed, 1 not exercised), exp34 cascaded tanks (K1-K4 met, no real step in the record), exp35 valve friction (inconclusive). exp37, the sealed worklist benchmark, had only 3 labelled problem loops out of 65 (no tuning or healthy labels), so by its frozen rule it is descriptive only: the ranking and the cause classification of the worklist are **not** validated, and its one concrete finding is an external-disturbance loop sent to a valve test. Engine gaps found are collected in issue #102.

**Validation.** RougherSim L5 rows: a badly tuned loop is detected and improved; a sticky valve is diagnosed as a valve, not a tuning problem; a loop driven by an external oscillation is not retuned; an averaging level is not tuned tight; rollback restores the previous parameters exactly. Owner decision 2026-11-17: public-data benchmarks replace blind worklist review and a real valve stroke test (separate issues).

**Gap to product.**

1. Online KPI job exists in the runtime; per operating mode is open (Phase 1).
2. Loop templates and vendor profiles through the catalogue (Phases 1 and 3).
3. Worklist ranking by criticality and benefit, fixed diagnosis order, outcomes (Phase 3).
4. Tuning path with preview, write in `confirm`, KPI check and rollback (Phase 3, needs Phase 2 gateway).
5. Optional step-test assistant (Phase 3, owner decision 2).

**Phase.** 1 (online KPIs) and 3 (product loop).

### 4.2 Virtual sensors

**Purpose.** Estimate any process variable from other tags when it is not measured, measured late and rarely, or measured by an instrument that can fail or drift. The module has four uses, all served by one engine:

| Use | Example | What the estimate does |
|---|---|---|
| **Quality inference** | Grade, P80, moisture from process tags between lab results or with a delayed analyser | Fills the gap between slow measurements |
| **Backup measurement** (analytical redundancy) | Belt-scale backup from conveyor drive power and belt speed; flowmeter backup from pump speed, power, pressures and density | Replaces a failed or out-of-service instrument |
| **Instrument validation** | Residual between the physical belt scale and its virtual twin | Detects drift, calibration error or a frozen transmitter; feeds anomaly detection (4.3) and loop monitoring (4.1) |
| **Unmeasured state** | Bin or sump inventory from a mass balance; specific energy (kWh/t) | Provides a variable nobody measures |

**Model structures.** The engine is not only data-driven. Each virtual sensor uses one of three structures:

- **Data-driven:** PLS, ridge/linear, one non-linear model (gradient boosting). Inputs and lags are proposed from data.
- **Physics template with fitted parameters:** a first-principles equation whose structure is fixed and whose parameters are fitted on plant data or entered from a datasheet. Examples: net drive power proportional to belt load; pump affinity laws plus head and power curves; valve flow from Cv(position), ΔP and density; hydrostatic level; a node mass balance.
- **Hybrid:** a physics template plus a data-driven correction of its residual.

**Presets.** For every typical industrial application the product ships a preset: a ready configuration that the user maps to the catalogue and may change in every field. A preset is data, not code: one file under `softsensor/presets/`, validated by `schemas/softsensor-preset.schema.json`. A preset defines:

- target variable, unit and physical range;
- **input roles**, not tag names (for example `drive_power`, `belt_speed`; required and optional roles, expected unit and range); the user binds each role to a catalogue tag, with a unit check;
- model structure, equation and parameters with default values, bounds and which are fitted;
- preprocessing defaults: lags, filters, validity ranges, missing-value handling;
- **validity conditions:** when the estimate is meaningful (pump running, belt loaded, valve opening within the trusted Cv range, inside the calibration envelope); outside them the estimate is flagged invalid;
- calibration procedure: against the physical instrument while it is healthy, against lab or analyser, or from datasheet values only;
- quality metrics and the naive baseline it must beat (last lab value, last good instrument value, constant).

Default values in a preset come from public sources with a row in `docs/PROVENANCE.md`, never from a plant. A customised preset is saved as a versioned project configuration; the shipped preset stays unchanged. "Custom" (data-driven, no preset) is always available.

**Preset catalogue.** Owner decision 2026-11-17: presets marked **v1** are the first-release set; `backup` is in v1. The rest is the roadmap.

| Preset | Estimates | Typical inputs | Structure | v1 |
|---|---|---|---|---|
| Belt-scale backup | Solids mass flow, t/h; totalised tonnage | Drive power or current, belt speed, empty-belt power curve, (inclination, length) | Physics: net power ∝ load × speed; calibrated against the scale | **v1** |
| Pump flowmeter backup | Volumetric flow | Pump speed, motor power, discharge and suction pressure, density | Physics: affinity laws + head/power curves; hybrid correction for wear | **v1** |
| Valve flowmeter | Flow through a control valve | Valve position, upstream and downstream pressure, density, Cv curve | Physics: valve equation (IEC 60534 form) | **v1** |
| Slurry solids flow and density | Dry solids t/h, % solids | Volumetric flow, slurry density, solids SG | Physics: mass and volume balance; backup density from pump power and flow (hybrid) | **v1** |
| Cyclone overflow size | P80 or % passing | Cyclone pressure, feed density, feed flow, cyclones open | Hybrid: empirical classification model + data-driven correction; calibrated on lab | **v1** |
| Lab / analyser quality inference | Grade, recovery, moisture, any lab variable | Lagged process tags, optional analyser as reference input | Data-driven (existing engine) | **v1** |
| Inventory by mass balance | Bin, sump or tank inventory; unmeasured stream | Measured streams in and out, level where available | Physics: node mass balance with drift correction | **v1** |
| Level from pressure | Level | Bottom pressure, density, (top pressure) | Physics: hydrostatic | later |
| Mill load and throughput | Mill filling, fresh feed estimate | Mill power, bearing pressure, sound, water addition | Hybrid | later |
| Feeder throughput | t/h from a feeder | Feeder speed, bin level change | Physics + calibration | later |
| Heat-exchanger duty and fouling | Duty, outlet temperature, UA trend | Flows, inlet and outlet temperatures | Physics: energy balance | later |
| Steam or gas flow | Mass flow | Valve position, pressures, temperature | Physics: compressible valve or orifice equation | later |
| Specific energy | kWh/t | Power and throughput tags | Calculation | later |
| Data reconciliation of a node | Reconciled flows, gross-error flags | All redundant streams of a node | Weighted least squares | later |

**Operating modes of a deployed virtual sensor.**

- `shadow`: computed and compared with the physical instrument; the residual is logged and monitored. Default for backup and validation presets.
- `backup`: published as the substitute value when the physical instrument is judged bad (bad quality status, flatline, residual above limit, or a manual switch by the operator).
- `primary`: the only source of the variable (quality inference, unmeasured state).

Every estimate carries a quality status (good, uncertain, bad, mapped to OPC UA status codes) and an uncertainty band from calibration residuals. Recalibration is proposed, not applied silently, when the residual against a healthy instrument drifts; bias correction is switchable and its parameters live in the schema.

**Boundary with the control system.** Crosscut writes only the virtual sensor's output tag, through the Write Gateway (section 5). Whether a loop uses the backup value as its PV is decided by DCS logic, which reads the output tag and its quality; Crosscut never switches a controller's PV source or mode.

**Ships today.** The engine (`softsensor/`) is generic with respect to tags, but:

- it supports PLS only and runs offline only (no runtime job);
- configurations are edited through the schema-generated form and the catalogue (a generated default config follows the catalogue mapping);
- **reference inputs** (#13) exist: a reference measurement (for example an online analyser) enters the model as a causal window mean with a coverage validity check and an EWMA bias check against the lab value; a lab alignment scan exists (`docs/target-alignment.md`);
- **backup mode** exists in the engine (#82, #100): it substitutes only rows the model marks valid; an invalid estimate gives quality `unavailable`, never `substituted`; an analyser flag with a missing value is treated as unknown and invalid. It is not deployed as a runtime job, and the validation protocol (`docs/softsensor-backup-validation-protocol.md`) is not yet completed;
- bias correction parameters are constants in `softsensor/.../bias.py`;
- there are no physics templates, presets, operating modes or uncertainty band.

**Validation cases.** The plant-1 analyser work (exp31, `tools/analyzer_vs_lab.py`, `tools/lab_extract.py`) is the validation case for quality inference, not a feature in itself; it is absorbed in Phase 4a. Every v1 preset gets an L5 row against RougherSim: ground truth from the simulator, and a fault-injection scenario that fails the physical instrument and checks failover and accuracy. RougherSim must expose the signals the presets need (drive power and belt speed, pump speed, power and pressures, valve position, cyclone pressure); where it does not yet, that is a RougherSim milestone item, not Crosscut code. Simulator results are not plant claims.

**Gap to product (Phase 4a).**

1. Preset schema, preset loader and the v1 presets, each with a PROVENANCE row before implementation.
2. Physics-template and hybrid structures beside the data-driven library (PLS, ridge/linear, gradient boosting); always blocked CV; comparison table against the preset's naive baseline.
3. Target types lab, analyser, physical instrument, or none, as user configuration: stamp meaning (start, end, or middle plus offset), composite sample window, analyser latency, missing codes and validity ranges. Lag search. (The explicit `reference input` exists; the rest is open.)
4. Validity conditions, quality status, uncertainty band, and the `shadow` / `backup` / `primary` modes with failover rules in the runtime. Residuals published to anomaly detection.
5. GUI wizard: choose preset or custom → bind roles to catalogue tags → accept or edit parameters (pump curve points, Cv table, belt data, or fit from data) → calibrate on a window → validation report → choose mode → deploy to runtime → optionally write the estimate to a DCS tag through the gateway.

**Phase.** 4a.

### 4.3 Anomaly detection and predictive maintenance (part of monitoring)

**Purpose.** Tell the engineer early that something is going wrong, where, and how much time is left to act. Three levels share one engine:

| Level | Question | Typical signals |
|---|---|---|
| **Process anomaly** | Is the plant behaving differently from its normal operation in this operating mode? | Many process tags at once (multivariate) |
| **Instrument health** | Is this transmitter frozen, drifting, noisy or out of calibration? | The tag itself, its redundant or virtual twin (4.2), loop behaviour (4.1) |
| **Equipment health** (predictive maintenance) | Is this pump, conveyor, mill, motor or valve degrading, and how fast? | DCS and historian tags: power and current, bearing and winding temperatures, pressures, flow against speed, overall vibration values imported as tags |

**Primary unit: the equipment (owner decisions 2026-11-20).** Anomaly detection is organised around **equipment** of the catalogue (pump, motor, agitator, conveyor, or a single process loop), not around hand-picked tag sets. The catalogue hierarchy area -> equipment -> loops and condition signals is filled from tag names by the regex naming rules (group `equipment`, #209) and confirmed in the GUI (#214). An equipment item carries its loops (PV/SP/OUT/MODE, FB) and optional **condition signals**: temperature, current or power, torque, vibration, speed. A loop without equipment is a one-loop equipment; a shared loop has one primary owner. The system **learns the normal operation of each equipment item by itself** (#215): it chooses training windows from the historian (equipment running, loops in AUTO, outputs not saturated, no open events, healthy loop KPIs, several operating points, per operating mode); the user sees the proposed windows and may exclude spans, but does not have to pick them. Methods are classical and explainable first: PCA with lags over all variables of the equipment (contributions give the diagnosis), expected-value regression of each condition signal from the operating point (residual = actual - expected), EWMA/CUSUM on residuals, time to a user limit with an uncertainty band. Deep models enter only as registered candidates (8.2) that beat this baseline on public data under a frozen protocol. Live, the runtime scores every learned equipment item (#216), suppressed while it is stopped, and raises one event per equipment, broken down into its loops and signals: loop behaviour ("OUT higher than usual for this SP and inflow") and equipment condition ("motor current +12 % against expected for 3 days, rising"). With too little quiet data the engine falls back to per-loop models and says so. The free-tag PCA detector stays as an advanced option; asset templates (below) add asset-specific knowledge on top of the same equipment model later. The design rules below apply unchanged.

Spectral vibration analysis, oil analysis and thermography are out of scope: their results enter Crosscut as tags from the systems that produce them.

**Processing chain.** The module follows the layer structure of ISO 13374 (condition monitoring data processing): data acquisition → data manipulation (cleaning, missing codes, resampling, features) → state detection (is it abnormal?) → health assessment (what is degrading, how badly?) → prognosis (how long until a limit?) → advisory (what to do, for whom). Each layer has its own output in the console and in the audit log, so an engineer can see where a conclusion came from.

**Design rules** (from public practice in process monitoring, alarm management and condition-based maintenance; each source gets a row in `docs/PROVENANCE.md` before implementation):

1. **Operating context first.** A model knows the operating mode. The user defines modes as conditions on catalogue tags (stopped, start-up, normal, high throughput, ore change, cleaning); the engine may propose modes by clustering history, and the user accepts them. Every detector has limits per mode. In non-process states (equipment stopped, start-up, shutdown) detectors are suppressed, not alarming. A single model for a multi-mode plant is the most common cause of false alarms.
2. **Normal data is chosen by a person and recorded.** The training window is picked in the GUI, known events are excluded and the exclusions are stored with the model. Minimum quiet data per mode is a schema parameter (configured by the site user, decision 2026-11-17; example: ≥ 2 weeks plus labelled events).
3. **Expected value and residual for equipment.** An equipment health indicator is the difference between what the asset does and what it should do under the same conditions: bearing temperature against load, speed and ambient; pump power and head against flow, speed and density (the pump-curve template of 4.2); drive power against belt load; valve travel against command (4.1 valve checks). The residual removes the effect of operating point, so a static high limit does not miss a fault at low load.
4. **Adaptation is gated and visible.** Limits and models may follow slow normal change, but updates happen only in steady, healthy operation and never absorb an open event. An update is proposed, versioned and accepted by the engineer, never silent.
5. **Few, meaningful notifications.** Crosscut events are advisory notifications in the console, not DCS alarms, but they follow alarm-management practice (ANSI/ISA-18.2, EEMUA 191): delay-on and delay-off (persistence), hysteresis, priority from consequence and time to respond, shelving with a reason and expiry, suppression by operating state, and grouping of correlated detections into one event with one root candidate. A notification budget per user role is configured and tracked; exceeding it is itself shown as a health problem of the monitoring.
6. **Diagnosis, not only detection.** Each event names the contributing tags, their time order (what moved first), and context from the catalogue: loop in manual, valve saturated, stale transmitter, virtual-sensor residual, recent setpoint change. Where a failure-mode table exists for the asset, the event lists the likely failure modes.
7. **Feedback closes the loop.** Every event gets an outcome from the user: confirmed fault, instrument problem, process change, false alarm, unknown; optionally a work-order reference. Outcomes build the labelled set, give per-detector precision, and show drift: a detector whose precision falls is flagged for review.
8. **Lead time is the value.** For equipment, the useful result is warning before functional failure (the P-F interval). Prognosis is shown as **time to limit**: the trend of a health indicator extrapolated to a user limit, with an uncertainty band. Remaining-useful-life claims are not made until real failure histories exist for that asset type.
9. **Criticality first.** The user ranks assets by consequence of failure; the GUI starts with the few assets that stop the line. Monitoring every tag at once is not the goal.
10. **Honest evaluation.** Detectors are evaluated per event: events detected, lead time before the known event, false events per week per mode, time to detect. Point-adjusted F1 is not used, as it overstates performance (Kim et al., AAAI 2022). Protocols are frozen before the run (section 8).

**Asset templates.** As with virtual-sensor presets, each typical asset type has a template: data under `anomaly/templates/`, validated by `schemas/asset-template.schema.json`, fully editable, defaults from public sources. A template defines input roles, health indicators (expected-value models and residuals), failure modes with the indicators that reveal them (in the spirit of ISO 17359), operating-mode conditions, notification rules and default priority.

| Template | Indicators (examples) | Failure modes shown | v1 |
|---|---|---|---|
| Centrifugal slurry pump | Power and head against flow, speed, density; bearing temperature residual; suction pressure margin | Impeller and liner wear, cavitation risk, bearing degradation, blockage | **v1** |
| Belt conveyor | Drive power against belt load; motor current balance; belt-scale against virtual twin (4.2); tracking and slip switches | Increased friction, idler or pulley failure, slip, scale drift | **v1** |
| Motor and gearbox | Winding and bearing temperature residual against load and ambient; current imbalance; overall vibration tag trend | Bearing wear, cooling loss, overload, misalignment | **v1** |
| Control valve | Travel deviation, stiction and deadband indicators (4.1), output saturation, actuator pressure | Stiction, actuator or positioner fault, wrong sizing | **v1** |
| Transmitter | Frozen value, noise change, drift against redundant or virtual twin | Frozen, drifting or failed instrument | **v1** |
| Grinding mill | Power against load and feed, bearing pressure, liner-wear trend against tonnage | Overload, liner wear, lubrication problem | later |
| Hydrocyclone cluster | Pressure against flow and density, overflow density | Roping, blocked apex, worn cyclone | later |
| Flotation cell | Agitator power, air flow against valve, level control quality | Agitator wear, air-line blockage | later |
| Thickener | Rake torque trend, underflow density against pump speed | Bogging risk, underflow line blockage | later |
| Compressor or blower | Pressure ratio against flow and power, discharge temperature | Fouling, efficiency loss, valve problems | later |

**Boundary with the control system.** The module never writes a setpoint or a controller parameter. It can publish an asset health index or an event flag to a DCS tag through the Write Gateway, on the same path as virtual-sensor outputs (section 5). A work request to a maintenance system (CMMS) is a later export, not a write to the plant.

**Ships today.** PCA with T2 and SPE, lagged columns, a stuck-sensor rule, a possible-ramp warning; an online `anomaly_scan` runtime job; active anomaly findings reach controller variable status (so a flagged CV or MV is handled by the controller host); the history store keeps the source quality code per sample. No operating modes in the detector, asset templates, expected-value models, notification management, outcomes or prognosis.

**Diagnostic readiness is NOT established.** exp29 met its criteria on simulated data only. On public real data the engine did not hold up: exp36 (SKAB and 3W) and exp38 (PRONTO) **missed every frozen target**. A model fitted on a short single-set-point window treats most quiet data as anomalous (PRONTO: 0.96 of quiet samples inside an event, 199.8 false events per quiet day against a target of 3; detection rate 0.59 against 0.70, which says little because events are open nearly all day). The anomaly engine does not transfer to real data yet; treat its output as an experimental advisory signal. Engine gaps found on public data are collected in issue #102.

**Validation.** RougherSim injects degradations with ground truth (pump wear, rising bearing temperature, belt friction, valve stiction, transmitter drift and freeze) and operating-mode changes that must **not** produce events. Each v1 template gets an L5 row: detection, lead time and false events per mode under a frozen protocol. Degradation injection is a RougherSim milestone item where it does not exist yet. Owner decision 2026-11-17: validation uses public data; asset-template work is deferred to Phase 4b.

**Gap to product.**

1. Online monitoring job exists in the runtime; operating modes and per-mode limits are open (Phase 1).
2. Configuration is editable through the generated form; a dedicated editor for normal-window selection with exclusions, mode definitions and detector settings is open (Phase 1).
3. Event management: persistence, hysteresis, priority, shelving, suppression by state, grouping, budget, outcomes and per-detector precision (Phase 3).
4. Instrument-health view tied to loop monitoring and virtual-sensor residuals (Phase 3).
5. Asset templates, expected-value models, health index, time to limit and the GUI asset view ranked by criticality (Phase 4b, sharing the preset machinery of 4.2).

**Phase.** 1 (online job), 3 (product view, event management, instrument health) and 4b (asset templates and predictive maintenance).

### 4.4 Fuzzy / expert supervisor

**Purpose.** Capture the knowledge of experienced operators and process engineers as readable rules, and turn it into process-level advice (first validation case: feed rate), gated by loop state, explained, logged and confirmed by the operator.

**Graphical editing: the Strategy Canvas.** An expert strategy is drawn, not written. The engineer never edits a file or types code; every element below is a graphical editor over the same schema-validated configuration (ADR 009).

- **Canvas of blocks and wires.** Signals flow left to right through blocks the engineer places and connects: *inputs* (catalogue tags, virtual-sensor estimates, health indicators from 4.3, loop states from 4.1) → *conditioning* (filter, rate of change, moving average, delay, quality and range check) → *rule blocks* (fuzzy rule bases) → *combination* (priority, minimum or maximum, weighted sum, override) → *outputs* (advice text, setpoint move proposal with limits, handed to the Write Gateway). A strategy with many inputs becomes a chain of small rule blocks instead of one unreadable rule base.
- **Process states drawn as a state diagram.** States such as start-up, normal, overload, low feed or ore change are bubbles; transitions are conditions drawn as arrows. Each state switches its own rule blocks on or off, which is how operators already think ("when the mill is overloaded, only these rules matter").
- **Membership editor.** Each linguistic term ("low", "normal", "high", "rising") is a curve over the variable's real engineering range, with a histogram of historical values behind it. The engineer drags handles; values snap to sensible steps; a moving marker shows the current value and how strongly each term is active. Term colours are the same everywhere on the canvas.
- **Rule matrix and rule sentences.** Two-input rules are a coloured grid: click a cell and choose the output term. The same rules read as sentences ("IF mill load IS high AND power IS rising THEN feed change IS large decrease"). Every rule has a weight and an on/off switch. After a replay the grid shades each cell by how often it fired, which shows dead rules and operating regions no rule covers.
- **Live animation.** In runtime and in replay, wires show their current values, blocks show active terms and rule firing strength, and the active process state is highlighted. Clicking an output traces its explanation back through the canvas to the dominant rules; the same one-line reason goes to the operator display and the audit log.
- **Try before it acts.** What-if sliders on any input, replay over a historical period, backtest of the strategy output against what operators actually did, and two versions side by side on the same period.
- **Versions and visual diff.** Every change is a version; the diff shows moved curves, changed cells and rewired blocks. Import and export as JSON validated by a schema.
- **Strategy templates.** Starter strategies for typical applications (mill feed-rate supervisor, flotation level and air supervisor, thickener underflow supervisor), customised by the engineer like the presets of 4.2.

UX details and open questions live in `docs/design/fuzzy-studio.md`.

**Ships today.** Fuzzy Studio (full editing of variables and rules, versions, replay, backtest); advisory supervisor gated by module-1 loop state, explained by its dominant rules; hash-chained audit log with operator acknowledgement; modes `off` and `advisory`. The fuzzy supervisor also runs as the first APC controller in the runtime (section 3.2), proposing setpoint moves through the gateway within its limits. exp27 met its frozen criteria in simulation only. There is no block canvas, no state diagram, no fired-rule shading and no strategy template.

**Gap to product.** Strategy Canvas with blocks, wires, state diagram, live animation, fired-rule shading and templates. Advice becomes a write proposal to the gateway: `confirm` first, `supervised` later.

**Phase.** 1 (configuration editor) and 6 (Strategy Canvas and closed loop).

### 4.5 MPC

**Purpose.** Constrained multivariable control above the base PID layer.

**Ships today.** Nothing. There is a plan and a C++20 smoke test with a Python parity test.

**Plan (accepted 2026-11-19, epic #163).** Design and decisions: `docs/design/mpc-design-note.md` sections 7-8. MPC is the second controller type on the APC core; v1 controls measured CVs only.

| Stage | Scope | Exit criterion |
|---|---|---|
| 7.0 Test beds | Wood-Berry 2x2 for development; RougherSim M9 grinding circuit (MIMO, live ore-hardness DV, ground-truth gain matrix) for validation | Step responses match the ground truth |
| 7.1 Identification | Multi-MV step-test planner as `confirm` proposals; per-pair MIMO fit with quality gate; `ident_model` artifact; GUI model-matrix editor | Identified gains inside the ground-truth confidence interval |
| 7.2 Engine | Python reference (steady-state target and dynamic QP, OSQP); GUI pre-commissioning simulator against the current PID | L1 tests on known plants, infeasible QP, saturated MV |
| 7.3 Runtime | `controller.type = mpc`, advisory -> confirm -> supervised, bumpless start, console with predictions and active constraints | L5 rows on RougherSim |
| 7.4 C++ core | ADR 001 core with parity test | Parity; solve time below 10 % of the cycle |
| 7.5 Validation | Frozen protocol: MPC versus well-tuned PID and fuzzy under the same constraints | Repeatable advantage, or a reported miss |

**Phase.** 7.

### 4.6 ML and optimisation

**Purpose.** Operating-range recommendation and an economic layer (RTO) above MPC and fuzzy.

**Ships today.** Nothing. The only "ML" in the repository is PLS and PCA.

**Plan (accepted 2026-11-19, epic #164).** Design: `docs/design/dml-operating-range-note.md`.

| Stage | Scope | Exit criterion |
|---|---|---|
| 8.1 Economic layer | Objective in the MPC steady-state target from per-site values and limits; GUI objective editor, benefit report | Higher value than setpoint-tracking MPC on RougherSim, no constraint violations |
| 8.2 Model registry | Versions (Phase PL), drift and model-mismatch monitoring for soft-sensor, anomaly and MPC models; retrain recommendation; GUI Models view | Degradation flagged within a frozen lead time |
| 8.3 Operating range | Descriptive envelope per mode, then DML with overlap, sensitivity and refusal outside the data; GUI question builder | Seven RougherSim cases including the expected hidden-confounder failure |
| 8.4 RTO | Steady-state flowsheet optimisation | Later; out of v1 |

**Phase.** 8.

## 5. Writing to the control system

ADR 012 ("Writes are a product capability", `docs/adr/012-writes-are-a-product-capability.md`) replaces the no-write position of ADR 010 and ADR 011. It is written alongside this document. The safety rules of ADR 011 keep their force.

- Only the Write Gateway writes. It is a separate process. Analysis packages never import write code and never hold credentials. CI guard tests now mean "only the gateway writes", not "nothing writes".
- Write policy is data (schema `write-policy`). Limits, maximum step, maximum rate, minimum interval, allowed loop modes, hold-off time, watchdog period, read-back tolerance. No override flag.
- Read-back verification of every write. Watchdog the control system can monitor. Operator priority: any manual change disables writing to that target for the hold-off time. Kill switch honoured within one gateway cycle, not bypassable by configuration. Hash-chained audit of every proposal, decision and write.
- Allowed targets: setpoints of loops in cascade or remote-setpoint mode; PID tuning parameters (`confirm` only); output tags of virtual sensors; bounded OUT tests in MAN (`confirm` only, ADR 017). OUT tests require site amplitude/duration/PV limits and verified return to pre-test OUT on PV trip, timeout, communication loss, mode change or cancellation. Crosscut never changes mode for an OUT test. The mode or setpoint-source node is written only for the setpoint handover of ADR 016 (release by default, take-remote only when a site enables it).
- Modes per target, default `off`: `off`, `advisory`, `dry_run`, `confirm`, `supervised`. Version 1 implements all five. PID tuning parameters are written in `confirm` only; `supervised` is allowed for loop setpoints and virtual-sensor tags within the policy. Authority is configurable per site under ADR 013/014 (decision 2026-11-17, #31).
- Authentication, roles (engineer, operator) and login are required before `confirm`. Local users only.
- The simulator of Phase 1a replaces the "soft PLC" of earlier plans. The 12 gateway scenarios become real tests against it in Phase 2.

## 6. DCS simulator (separate repository, Phase 1a)

A separate project that Crosscut sees only as a black box through OPC UA and historian export. Ground truth is exposed on a separate channel. It is the base for a future simplified flowsheet-modelling tool for metallurgists.

The repository is RougherSim (github.com/msurun/RougherSim, private, no licence, retained by decision 2026-11-17 (original decision 2026-10-27)); its plan is `docs/IMPLEMENTATION_PLAN.md` there, milestones M0-M7.

- **Process model as data.** Flowsheet JSON plus a unit library: feeder and conveyor with transport delay, ball mill, sump with pump, hydrocyclone, flotation bank of 3–4 cells with level and air (kinetic model), a simple cleaner, a concentrate thickener. Valves with deadband and stiction. Transmitters with noise, quantisation and historian compression. Separate mass balance for solids, water and minerals. Realistic couplings: integrating levels, inter-cell interaction, ore hardness and feed disturbances. About 20–30 PID loops including cascades. Starting point is the existing grinding model in `sim/`.
- **Vendor profile as a replaceable layer.** First ABB 800xA / AC 800M: OPC UA address space and 800xA-style naming; PID block semantics (Man/Auto/Cascade/Remote SP, tracking, bumpless, Gain/Ti/Td names and units); alarms and events; historian export format. We do not imitate Operator Workplace or Aspect Objects. Second profile: Siemens (PCS 7 / S7 PID).
- **Operating modes.** Real time and accelerated. Scripted operator actions. Fault injection. Scenario recording.
- **Validation limits (2026-11-17).** The ABB profile remains ASSUMPTION; public ABB documentation checks conventions, not real-stack conformance. No ABB SoftController for now. Siemens PLCSIM Advanced is deferred until a Siemens user appears.

The DCS simulator replaces the "soft PLC" for the gateway scenarios in Phase 2 and for the tuning cycle in Phase 3.

Tests of Crosscut against RougherSim are a product deliverable, not an afterthought: every phase exit that names the simulator maps to a row of the L5 acceptance matrix in `docs/TESTING_STRATEGY.md` (scenario, seed, pass criterion), run through the harness `tests/integration_roughersim/` against a pinned RougherSim version. Ground truth is read only by tests.

## 7. Phases

Every phase has a short detailed plan before its start and its own gates: `ruff`, `pytest` for the whole repository, `vitest`, `tsc`, `build`, `e2e:all`.

| Phase | Goal | Exit criteria |
|---|---|---|
| **Phase PG** — Console navigation (owner decision 2026-11-19, first in the plan) | Grouped 9-item menu, Overview start page, global status bar with approval queue, role-based menu, loop data in the catalogue, endpoints without a GUI resolved (`docs/design/screens.md`, #172-#177) | Every implemented feature reachable from the grouped menu; old routes redirect; e2e and axe green at 1280 and 390 px |
| **Phase 0** — Cleanup, no new features | This document replaces PROJECT_DESIGN. ADR 012 replaces the no-write position. Guard tests change meaning. `docs/archive/` for one-off plans and documents. `tools/` marked for absorption. Anti-drift rule in `CLAUDE.md`. GitHub milestones 0–8, with Phase 4 split into 4a and 4b. Closed experiment lines (stiction, ACF, idle) are **not** moved; `experiments/README.md` indexes their status | All gates green after moves. No dead links in docs. `git mv` preserves history |
| **Phase 1** — Online foundation | One connector interface (browse, metadata, history, live, write-through-gateway only). Project catalogue plus GUI editor. Runtime as an on-prem service. Generic configuration editor generated from `schemas/*.schema.json` | Simulated OPC UA server → catalogue built in the GUI → runtime computes live loop KPI and shows it in the console. No file edited by hand (e2e test) |
| **Phase 1a** — DCS simulator | See section 6 | Simulator runs as OPC UA server in ABB profile. Phase 1 Crosscut connects, builds the catalogue, computes live KPI. Mass balance closes (test). Loop step responses match ground truth |
| **Phase 2** — Write Gateway v1 | Implementation per ADR 012: `off`, `advisory`, `dry_run`, `confirm`, then `supervised`. First write protocol: OPC UA. Write policy schema and GUI editor. Proposal queue in the console. Roles and login | All 12 gateway scenarios pass against the Phase 1a DCS simulator. e2e shows proposal → confirm → write → read-back → audit entry; kill switch stops in one cycle. Gateway, policy and permissions pass review |
| **Phase 2.5** — APC core (owner decision 2026-11-10, before Phase 3) | Section 3.2 and ADR 015: one variable model in the catalogue, live variable status, loop readiness, controller host in the runtime, fuzzy supervisor as the first controller, operator console | Fuzzy supervisor runs as a controller in the runtime against RougherSim in closed loop: a bad CV is dropped, a lost MV or comms sheds to base control, restart restores the controller state, the operator switches controller and variables on and off in the console |
| **Phase 3** — Module 1 as a complete product (first release) | Online monitoring of all catalogue loops. Tuning path from detection to write after confirmation, KPI check, one-click rollback. Optional step-test assistant | Full cycle on the DCS simulator: weak loop detected → test → tuning → write after confirmation → KPI improvement → rollback works. Public-data benchmarks (decision 2026-11-17); site deployment checks are separate |
| **Phase 4a** — Universal virtual-sensor engine with presets | See section 4.2 | A lab-and-analyser configuration built entirely in the GUI is validated on public data (decision 2026-11-17). exp30 (synthetic) still meets its criteria. Every v1 preset, configured only in the GUI, passes its L5 row against RougherSim, including the instrument-failure scenario (failover and accuracy criteria frozen in the protocol before the run) |
| **Phase 4b** — Asset templates and predictive maintenance | See section 4.3 (asset templates, expected-value models, health index, time to limit). Builds on the preset machinery of Phase 4a and the event management of Phase 3 | Every v1 asset template detects its injected degradation in RougherSim with the lead time and false-event rate set in a frozen protocol, and raises no event on operating-mode changes. Asset view in the GUI ranked by criticality |
| **Phase 5** — Connectors | PI (PI Web API, optionally AF SDK); SQL/ODBC profiles (IP.21, PHD, AVEVA/Wonderware Historian, WinCC); OPC DA/HDA through a wrapper or proxy UA; Excel and Parquet | Each connector covers history, live read and metadata. Each has a test on a recorded fixture. Real-source tests are owner tasks. Writes stay gateway-only |
| **Phase 6** — Fuzzy closed loop | Strategy Canvas (section 4.4). Supervisor advice becomes setpoint write proposals through the gateway: `confirm` first, then `supervised` | Write proposals flow through the gateway; run in `confirm` then `supervised` tested against the DCS simulator |
| **Phase 7** — MPC | Identification from step tests and an editable model matrix in the GUI. Linear MPC with constraints (QP) checked on `sim/`. C++ runtime per ADR 001 | MPC writes setpoints through the gateway in `supervised` mode against the DCS simulator |
| **Phase 8** — ML and optimisation | Operating-range recommendation and an economic layer (RTO) above MPC and fuzzy | Plan accepted by the owner. Economic value per PV unit and limits entered by the site user; no decision blocker (2026-11-17, #35) |

**Phase 1 item 1 (#43): implemented.** Legacy CSV wide/long, SQL, OPC UA polling,
subscription and collector acquisition use connector adapters without changing their dataset
contracts. CSV history applies UTC bounds `[start, end)` and last-value sampling per requested
period for both layouts. See [Read connectors](CONNECTORS.md) for policy and compatibility details.

**Order of work (owner decision 2026-11-19).** Phase PG -> Phase 3 release items -> Phase PL -> Phase 7 (MPC) -> Phase 8.1 (economic layer) -> Phase 4a presets, Phase 8.2-8.3, Phase 4b, Phase 6. The phase numbers stay as names; this order replaces the numeric order. MPC v1 does not wait for Phase 4a because it controls measured CVs only.

**Phase PL - Platform lifecycle and deployment (added 2026-11-19, milestone "PL").** Runs after the
Phase 3 release items and before the Phase 4a presets: versioned catalogue and models with diff,
publish and approval (#165), dependency invalidation (#166), backup and restore without history
(#167), Windows installer (#168), Docker Compose (#169), observability in the GUI (#170). Exit
criterion: a configuration change is versioned, approved where required, reversible and restorable
on a fresh installation without a shell.

### 7.1 Feature status matrix (2026-11-19)

Four statuses per feature, kept apart on purpose: **Built** (code on main), **Evidence** (what
proves it works, and where), **GUI** (an engineer can do it without editing a file), **Deploy**
(ready for a site). "Sim" means RougherSim or `sim/` only, not a plant claim. Update this table in
the same PR that changes one of its rows.

| Feature | Built | Evidence | GUI | Deploy | Open issues |
|---|---|---|---|---|---|
| Console navigation (grouped menu, start page, status bar) | no (15 flat tabs) | - | - | - | #172-#177 |
| Read connectors (CSV, SQL/ODBC, PI Web API, OPC UA) | yes | recorded fixtures, sim | yes | no real-source test | #32 |
| Project catalogue | partly | e2e | editor and wizard; no versions, CSV bulk, mode proposals | no | #144, #145, #165, #166 |
| Operating modes used by modules | stored only | - | edit only | no | #146 |
| Loop KPI online | yes | L5-P1 live (catalogue built in code) | view yes, build path not proven | no | #151, #146 |
| Worklist and diagnosis | partly | exp37 descriptive only | yes | no | #149, #150, #152 |
| Identification and tuning report | yes | exp33 5/7 met, exp34 K1-K4 | yes | no | #147, #148 |
| PID write in confirm, KPI check, rollback | yes | sim (ADR 014, L5) | yes | no real DCS | #151 |
| Valve stroke and OUT tests in MAN | yes | sim; exp35 inconclusive | yes | no | #84 |
| Write Gateway (modes, policy, audit, kill switch) | yes | sim, 12 scenarios | yes | no real DCS | #153 |
| APC core and fuzzy controller | yes | L5 C rows, L5-P6 3/3 in sim | yes | no | - |
| Strategy Canvas | no | - | no | no | #162 |
| Soft sensor (PLS, reference input, backup in engine) | partly, offline | exp39: loses to lab persistence | generated form | no runtime job | #154-#159 |
| Anomaly (PCA, stuck, regimes) online | yes | exp40 missed, exp41 D2 only | yes | no | #160, #146 |
| Per-equipment anomaly with learned normal operation and condition signals | no | - | no | no | #214-#216 |
| Asset templates and predictive maintenance | no | - | no | no | #161 |
| MPC | no (design accepted) | - | no | no | #163, #178-#186 |
| Economic layer and ML | no (design accepted) | - | no | no | #164, #187-#191 |
| Config lifecycle, backup, installers, observability | no (systemd unit only) | - | no | no | #165-#170 |

## 8. Evidence discipline and claim limits

- Frozen protocols: an experiment freezes and commits its protocol before any run. Test seeds run once. Misses ship visibly; thresholds are not moved.
- Experiments serve the product features in this document. They are not a separate line of work.
- Simulator success is not a plant claim. Findings say "in our simulator, with our operator model".
- Owner decision 2026-11-17: validation uses public datasets; owner-site data is excluded from development and validation.

See `docs/TESTING_STRATEGY.md` (L0–L7 ladder), `docs/ASSUMPTIONS.md` (unproven assumptions and retirement plans), `experiments/README.md` (experiment index and status).

## 9. Anti-drift rule

Enforced for every task, and written into the repository `CLAUDE.md` in Phase 0:

1. Every task names the module and phase in this document.
2. Owner decision 2026-11-17: public-data work yields generic engine features; site facts remain user configuration.
3. A new top-level element (package, experiment line, tool) requires the owner's approval.

## 10. Owner decisions - 2026-11-17

| # | Decision (2026-11-17) | Follow-up |
|---|---|---|
| 1 | **2026-11-17:** ABB/Siemens validation access is a deployment datum: the site DCS, PidCC unit and access policy belong in the plant map and write policy, not in product decisions. | See decision |
| 2 | **2026-11-17:** The step-test assistant MAY propose OUT writes in manual, in `confirm` mode only. Implementation is a separate issue. | See decision |
| 3 | **2026-11-17:** RougherSim stays private with no licence, as decided 2026-10-27. Siemens PLCSIM Advanced verification is deferred until a Siemens user appears. | See decision |
| 4 | **2026-11-17:** No ABB SoftController for now. The ABB profile stays labelled ASSUMPTION; conventions are checked against public ABB documentation. | See decision |
| 5 | **2026-11-17:** ADR 008 (AGPL-3.0-only, with CLA) and ADR 009 accepted (#29). | See decision |
| 6 | **2026-11-17:** Blind worklist review is replaced by public-data benchmarks (separate issue). | See decision |
| 7 | **2026-11-17:** The real valve stroke test is replaced by public-data benchmarks (separate issue). | See decision |
| 8 | **2026-11-17:** The optimisation objective is per-site configuration: the user enters economic value per PV unit and operating limits, like item 9. Phase 8 is no longer blocked by a decision (#35). | See decision |
| 9 | **2026-11-17:** Write authority is configurable per site under ADR 013/014 and `docs/ADMIN_GUIDE.md`; no owner decision is pending (#31). | See decision |
| 10 | **2026-11-17:** Soft-sensor v1 consists of the presets marked v1 in section 4.2; `backup` mode IS in v1 (separate issue). Validation instruments use public data. | See decision |
| 11 | **2026-11-17:** Deferred to Phase 4b: v1 asset templates are those marked in section 4.3; validation uses public data. | See decision |

Owner decision 2026-11-17: Crosscut is a framework, not a setup for one plant. Plant data from the owner's site is not used for development or validation. Validation uses public datasets; site facts (tunings, sample metadata, vendor conventions, economic values) are per-site configuration entered by the user. Check the licence before use and add a row to `docs/PROVENANCE.md`; download to a scratch folder outside the repository; never commit or redistribute data. CC BY-SA and unlicensed datasets are used locally only; no derived data is published.

### Owner decisions - 2026-11-19

| # | Decision (2026-11-19) | Follow-up |
|---|---|---|
| 1 | Deployment ships both a Windows installer (services and console) and Docker Compose for Linux on-prem. | #168, #169 |
| 2 | Publishing a new catalogue or model version needs a second person (controls engineer) only when the change touches loops or controller variables with active writes; otherwise one engineer publishes. | #165 |
| 3 | Backup and restore cover configuration, models, policies, users and audit, not the Parquet history; history stays in the source historian. | #167 |
| 4 | Phase PL (platform lifecycle and deployment) is added between the Phase 3 release items and the Phase 4a presets. | section 7 |
| 5 | Phase PG (console navigation) is the first step of the plan; Advisor moves under Fuzzy, Steps and Tuning proposals under Loops, Catalogue/Import/Onboarding under Site, Runtime/Gateway/Users under Administration. | #172-#177 |
| 6 | Order of work: PG, Phase 3 release, PL, Phase 7 MPC, Phase 8.1, then 4a presets, 8.2-8.3, 4b, 6. | section 7 |
| 7 | MPC test beds: Wood-Berry (development) and RougherSim grinding circuit (validation); v1 measured CVs only. | #178, RougherSim M9 |
| 8 | MPC model refresh is started by the engineer from the GUI on a model-mismatch recommendation; `supervised` allowed, enabled by the controls engineer. | #184 |
| 9 | MPC defaults: cycle 30-60 s, `Np` = settling time / cycle, `Nc` 5-10; infeasible plan relaxes CVs by priority, holds MVs, sheds after 3 cycles. | #182 |
| 10 | QP solver OSQP (Apache-2.0) in Python and C++. | #182, #185 |
| 11 | DML: the user picks `T`, `Y` and `X` in a GUI question builder; the objective stays per-site configuration. | #190 |

### Owner decisions - 2026-11-20

| # | Decision (2026-11-20) | Follow-up |
|---|---|---|
| 1 | Analysis works on catalogue sources (PI, historian, SQL) and live loops, not on dataset copies; datasets become an internal cache. | #201-#203, #212 |
| 2 | Loop knowledge (ranges, dead time, ultimate period, process kind) is proposed from source metadata and history with evidence and confirmed by the user; the amplitude limit stays a user decision. | #213 |
| 3 | Loops are found from tag names by ordered regex naming rules with a live tester and presets. | #209 |
| 4 | Anomaly detection is per equipment: loops and condition signals (temperature, current/power, torque, vibration) are grouped into equipment by regex naming rules; the system learns normal operation of each equipment item by itself with classical, explainable ML first (PCA, expected-value regression, residual drift); deep models only if they beat this baseline under a frozen protocol (section 4.3). | #209, #214-#216 |

## 11. Document map

| Document | Use |
|---|---|
| `README.md` | Status, per-module claim limits, quick start |
| `docs/PRODUCT.md` | This document: the single product definition |
| `docs/PRODUCT.pl.md` | Polish companion of this document |
| `docs/HANDOFF.md` | State of work, real-data notes, working rules |
| `docs/IMPLEMENTATION_LOG.md` | Per-step implementation detail |
| `docs/TESTING_STRATEGY.md` | L0–L7 ladder, fault-injection catalogue, backlog |
| `docs/ASSUMPTIONS.md` | Unproven assumptions and retirement plans |
| `docs/PROVENANCE.md` | Public sources and third-party datasets |
| `docs/OWNER_TASKS.md` | What only the owner can do; what to bring back |
| `docs/adr/001` | C++ runtime, Python offline tooling (accepted) |
| `docs/adr/008` | AGPL-3.0-only with CLA (accepted 2026-11-17, #29) |
| `docs/adr/009` | Configuration is data (accepted 2026-11-17, #29) |
| `docs/adr/010` | Advisory supervisor (accepted 2026-11-17; partly superseded by ADR 012 and ADR 015) |
| `docs/adr/011` | Write path design; owner open points closed by ADR 013/014 defaults (2026-11-17, #31); safety rules still in force |
| `docs/adr/012` | Writes are a product capability |
| `docs/adr/013` | Roles and authority |
| `docs/adr/014` | Tuning write path |
| `docs/adr/015` | APC core: shared variable model and controller host (Phase 2.5) |
| `docs/adr/016` | Setpoint handover (mode writes) |
| `docs/adr/017` | Manual-output step tests |
| `experiments/README.md` | Experiment index and status (closed lines stay in place) |
| `docs/archive/` | One-off plans and documents |
| `docs/PROJECT_DESIGN.md` | Historical record only; not maintained |
