# Crosscut Process Suite — Product definition

This document is the single product definition of the Crosscut Process Suite. It replaces `docs/PROJECT_DESIGN.md`, which is kept only as a historical record. The ADRs in `docs/adr/` override this document where they conflict. Date: 2026-10-27.

## 1. Product definition

Crosscut is an on-prem server with a browser console in which a process engineer configures the system **without programming** (the *no-code* principle): they connect a historian or DCS of any vendor, analyse and model the process (loops, virtual sensors, anomalies, rules, MPC, optimisation), run the models online, and change setpoints in the control system through one safe **Write Gateway**, in modes `advisory` → `confirm` → `supervised`.

| User | Role |
|---|---|
| Process engineer | Connects sources, builds the project catalogue, designs and deploys models. Owns no-code configuration. |
| Operator | Works the console, accepts or rejects proposed writes in `confirm` mode. |
| Controls engineer | Owns the write policy, the gateway configuration and the safety settings. Supervises anything that touches a controller. |

Principles that do not change: plant data validates features and never defines them. No tag name, unit, missing-value code, window or threshold of one plant may be a constant in `*/src`. Every feature works on any tag, lab, analyser and loop the user configures. Real plant data stays outside the repository.

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
| **Connect** | Read history and live values, browse metadata; write only through the gateway | CSV wide/long import, SQLite and any DB-API/ODBC connection (pyodbc is not a dependency), OPC UA polling and subscription, a Parquet collector | One connector interface. No PI Web API, IP.21, PHD, AVEVA, OPC DA/HDA |
| **Project catalogue** | Sources, tags, units, ranges, missing codes, time zone, loops (PV/SP/OUT/mode/PID parameters in vendor form), lab definitions; edited in the GUI | Does not exist. Import settings (missing codes, −9999 sentinel) live in `loops/.../plant_import.py` as code-level settings | Whole layer. The −9999 default constant must be removed (issue #42) |
| **Engines** | Offline design mode and online run mode for each module | Loops, fuzzy, supervisor, anomaly, soft sensor: offline, on demand, over a stored window | Online run mode. Generic schema-driven configuration editor |
| **Runtime** | On-prem service (Windows service or systemd) runs deployed jobs cyclically: loop KPI, anomaly scan, soft-sensor estimate, fuzzy advice. Status, error log, start/stop from the GUI | Does not exist | Whole layer |
| **Write Gateway** | Separate process. Writes proposals only. Policy as data, read-back, watchdog, operator priority, kill switch, audit | `gateway/` holds interfaces and 12 strict-xfail scenarios. Write code exists only against a simulator | Full implementation (Phase 2) |
| **Web console** | Browser UI: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import, Steps | React + TypeScript frontend, e2e suite green. Some configurations are read-only in the GUI | Configuration editing for supervisor, anomaly and soft sensor; proposal queue; login and roles |

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

**Ships today.** `schemas/project.schema.json` and `schemas/tags.schema.json` (loops, variables, tags) and CSV/SQL import with missing-value settings held at code level in `loops/.../plant_import.py`. No GUI editor, no source binding, no equipment hierarchy, operating modes, labs or vendor profiles. The default −9999 constant must be removed (issue #42).

**Phase.** 1.

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

**Valves.** Guided stroke test (a write of OUT in manual is open owner decision 2), stiction quantification, valve-health trend shared with the valve asset template (4.3).

**Benefit and reports.** Benefit estimate: variance reduction → possible setpoint move toward a limit → value per year, using the value per unit of PV entered by the user (open owner decision 8 for the economic layer). Shift and weekly loop report: what changed, what was fixed, what still waits.

**Ships today.** Worklist with findings (manual, saturated, flatline, oscillating); ACF oscillation test and oscillation clusters; valve health KPIs, stiction suspicion and guided stroke test; closed-loop and step identification (FOPDT, integrating experimental) with a quality gate; tuning report (SIMC/AMIGO, cascade planning); benefit estimate; Steps view. All offline and on demand. No loop templates, no per-mode KPIs, no cause ordering in the worklist, no outcomes, no write, KPI check or rollback.

**Validation.** RougherSim L5 rows: a badly tuned loop is detected and improved; a sticky valve is diagnosed as a valve, not a tuning problem; a loop driven by an external oscillation is not retuned; an averaging level is not tuned tight; rollback restores the previous parameters exactly. Plant evidence: blind worklist review and one real valve stroke test (owner tasks), then the Phase 3 pilot in `confirm`.

**Gap to product.**

1. Online KPI job in the runtime, per operating mode (Phase 1).
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

**Preset catalogue.** Proposed first-release set marked **v1**; the rest is the roadmap. The final v1 set is an owner decision (section 10).

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

- it supports PLS only and runs offline only;
- the GUI can only read a configuration; a new configuration can be added only with the "Load example" button;
- there is no `reference input` in the code. An online analyser can only be an ordinary input tag. PROJECT_DESIGN §4.4 claimed a reference input exists; this document corrects that;
- bias correction is always on; its parameters are constants in `softsensor/.../bias.py`;
- there are no physics templates, presets, validity conditions, operating modes or quality status.

**Validation cases.** The plant-1 analyser work (exp31, `tools/analyzer_vs_lab.py`, `tools/lab_extract.py`) is the validation case for quality inference, not a feature in itself; it is absorbed in Phase 4a. Every v1 preset gets an L5 row against RougherSim: ground truth from the simulator, and a fault-injection scenario that fails the physical instrument and checks failover and accuracy. RougherSim must expose the signals the presets need (drive power and belt speed, pump speed, power and pressures, valve position, cyclone pressure); where it does not yet, that is a RougherSim milestone item, not Crosscut code. Simulator results are not plant claims.

**Gap to product (Phase 4a).**

1. Preset schema, preset loader and the v1 presets, each with a PROVENANCE row before implementation.
2. Physics-template and hybrid structures beside the data-driven library (PLS, ridge/linear, gradient boosting); always blocked CV; comparison table against the preset's naive baseline.
3. Target types lab, analyser, physical instrument, or none, as user configuration: stamp meaning (start, end, or middle plus offset), composite sample window, analyser latency, missing codes and validity ranges. Lag search. Explicit `reference input`.
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

Spectral vibration analysis, oil analysis and thermography are out of scope: their results enter Crosscut as tags from the systems that produce them.

**Processing chain.** The module follows the layer structure of ISO 13374 (condition monitoring data processing): data acquisition → data manipulation (cleaning, missing codes, resampling, features) → state detection (is it abnormal?) → health assessment (what is degrading, how badly?) → prognosis (how long until a limit?) → advisory (what to do, for whom). Each layer has its own output in the console and in the audit log, so an engineer can see where a conclusion came from.

**Design rules** (from public practice in process monitoring, alarm management and condition-based maintenance; each source gets a row in `docs/PROVENANCE.md` before implementation):

1. **Operating context first.** A model knows the operating mode. The user defines modes as conditions on catalogue tags (stopped, start-up, normal, high throughput, ore change, cleaning); the engine may propose modes by clustering history, and the user accepts them. Every detector has limits per mode. In non-process states (equipment stopped, start-up, shutdown) detectors are suppressed, not alarming. A single model for a multi-mode plant is the most common cause of false alarms.
2. **Normal data is chosen by a person and recorded.** The training window is picked in the GUI, known events are excluded and the exclusions are stored with the model. Minimum quiet data per mode is a schema parameter (the plant default stays an owner task: ≥ 2 weeks plus labelled events).
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

**Ships today.** PCA with T2 and SPE, lagged columns, a stuck-sensor rule, a possible-ramp warning. exp29 round 3 met its criteria. No operating modes, asset templates, expected-value models, notification management, outcomes or prognosis.

**Validation.** RougherSim injects degradations with ground truth (pump wear, rising bearing temperature, belt friction, valve stiction, transmitter drift and freeze) and operating-mode changes that must **not** produce events. Each v1 template gets an L5 row: detection, lead time and false events per mode under a frozen protocol. Degradation injection is a RougherSim milestone item where it does not exist yet. Real evidence needs owner data: quiet periods per mode and labelled events, ideally with maintenance history.

**Gap to product.**

1. Online monitoring job in the runtime with operating modes and per-mode limits (Phase 1).
2. Configuration editable in the GUI (supervisor and anomaly configurations are read-only today): normal-window selection with exclusions, mode definitions, detector settings (Phase 1).
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

**Ships today.** Fuzzy Studio (full editing of variables and rules, versions, replay, backtest); advisory supervisor gated by module-1 loop state, explained by its dominant rules; hash-chained audit log with operator acknowledgement; modes `off` and `advisory`. exp27 met its frozen criteria in simulation. There is no block canvas, no state diagram, no fired-rule shading and no strategy template; supervisor configuration is read-only in the GUI.

**Gap to product.** Supervisor configuration editable in the GUI (generic editor in Phase 1). Strategy Canvas with blocks, wires, state diagram, live animation, fired-rule shading and templates. Advice becomes a write proposal to the gateway: `confirm` first, `supervised` later.

**Phase.** 1 (configuration editor) and 6 (Strategy Canvas and closed loop).

### 4.5 MPC

**Purpose.** Constrained multivariable control above the base PID layer.

**Ships today.** Nothing. There is a plan and a C++20 smoke test with a Python parity test.

**Gap to product.** Identification from step tests (Steps view plus a generalised driver-response tool), an editable model matrix in the GUI, linear MPC with constraints (QP), C++ runtime per ADR 001, setpoint writes through the gateway in `supervised` mode.

**Phase.** 7.

### 4.6 ML and optimisation

**Purpose.** Operating-range recommendation and an economic layer (RTO) above MPC and fuzzy.

**Ships today.** Nothing. The only "ML" in the repository is PLS and PCA.

**Gap to product.** Real historian data, a checkable confounding analysis, the economic objective and limits (owner decision, not decided). Plan of work to be proposed by the assistant and accepted by the owner.

**Phase.** 8.

## 5. Writing to the control system

ADR 012 ("Writes are a product capability", `docs/adr/012-writes-are-a-product-capability.md`) replaces the no-write position of ADR 010 and ADR 011. It is written alongside this document. The safety rules of ADR 011 keep their force.

- Only the Write Gateway writes. It is a separate process. Analysis packages never import write code and never hold credentials. CI guard tests now mean "only the gateway writes", not "nothing writes".
- Write policy is data (schema `write-policy`). Limits, maximum step, maximum rate, minimum interval, allowed loop modes, hold-off time, watchdog period, read-back tolerance. No override flag.
- Read-back verification of every write. Watchdog the control system can monitor. Operator priority: any manual change disables writing to that target for the hold-off time. Kill switch honoured within one gateway cycle, not bypassable by configuration. Hash-chained audit of every proposal, decision and write.
- Allowed targets: setpoints of loops in cascade or remote-setpoint mode; PID tuning parameters (`confirm` only); output tags of virtual sensors. Never the controller output or the mode. A step-test assistant writing OUT in manual is an open owner decision (section 10).
- Modes per target, default `off`: `off`, `advisory`, `dry_run`, `confirm`, `supervised`. Version 1 implements all five. PID tuning parameters are written in `confirm` only; `supervised` is allowed for loop setpoints and virtual-sensor tags within the policy. Who may enable `supervised` is an owner decision (section 10).
- Authentication, roles (engineer, operator) and login are required before `confirm`. Local users only.
- The simulator of Phase 1a replaces the "soft PLC" of earlier plans. The 12 gateway scenarios become real tests against it in Phase 2.

## 6. DCS simulator (separate repository, Phase 1a)

A separate project that Crosscut sees only as a black box through OPC UA and historian export. Ground truth is exposed on a separate channel. It is the base for a future simplified flowsheet-modelling tool for metallurgists.

The repository is RougherSim (github.com/msurun/RougherSim, private, no licence yet); its plan is `docs/IMPLEMENTATION_PLAN.md` there, milestones M0-M7.

- **Process model as data.** Flowsheet JSON plus a unit library: feeder and conveyor with transport delay, ball mill, sump with pump, hydrocyclone, flotation bank of 3–4 cells with level and air (kinetic model), a simple cleaner, a concentrate thickener. Valves with deadband and stiction. Transmitters with noise, quantisation and historian compression. Separate mass balance for solids, water and minerals. Realistic couplings: integrating levels, inter-cell interaction, ore hardness and feed disturbances. About 20–30 PID loops including cascades. Starting point is the existing grinding model in `sim/`.
- **Vendor profile as a replaceable layer.** First ABB 800xA / AC 800M: OPC UA address space and 800xA-style naming; PID block semantics (Man/Auto/Cascade/Remote SP, tracking, bumpless, Gain/Ti/Td names and units); alarms and events; historian export format. We do not imitate Operator Workplace or Aspect Objects. Second profile: Siemens (PCS 7 / S7 PID).
- **Operating modes.** Real time and accelerated. Scripted operator actions. Fault injection. Scenario recording.
- **Limitation to state openly.** The imitation proves our understanding of 800xA, not conformance with a real 800xA. Real-stack checks: Siemens PLCSIM Advanced trial (cheap check of the Siemens profile); ABB SoftController only with a legal ABB licence, in a legal environment, done by the owner. No unofficial downloads.

The DCS simulator replaces the "soft PLC" for the gateway scenarios in Phase 2 and for the tuning cycle in Phase 3.

Tests of Crosscut against RougherSim are a product deliverable, not an afterthought: every phase exit that names the simulator maps to a row of the L5 acceptance matrix in `docs/TESTING_STRATEGY.md` (scenario, seed, pass criterion), run through the harness `tests/integration_roughersim/` against a pinned RougherSim version. Ground truth is read only by tests.

## 7. Phases

Every phase has a short detailed plan before its start and its own gates: `ruff`, `pytest` for the whole repository, `vitest`, `tsc`, `build`, `e2e:all`.

| Phase | Goal | Exit criteria |
|---|---|---|
| **Phase 0** — Cleanup, no new features | This document replaces PROJECT_DESIGN. ADR 012 replaces the no-write position. Guard tests change meaning. `docs/archive/` for one-off plans and documents. `tools/` marked for absorption. Anti-drift rule in `CLAUDE.md`. GitHub milestones 0–8, with Phase 4 split into 4a and 4b. Closed experiment lines (stiction, ACF, idle) are **not** moved; `experiments/README.md` indexes their status | All gates green after moves. No dead links in docs. `git mv` preserves history |
| **Phase 1** — Online foundation | One connector interface (browse, metadata, history, live, write-through-gateway only). Project catalogue plus GUI editor. Runtime as an on-prem service. Generic configuration editor generated from `schemas/*.schema.json` | Simulated OPC UA server → catalogue built in the GUI → runtime computes live loop KPI and shows it in the console. No file edited by hand (e2e test) |
| **Phase 1a** — DCS simulator | See section 6 | Simulator runs as OPC UA server in ABB profile. Phase 1 Crosscut connects, builds the catalogue, computes live KPI. Mass balance closes (test). Loop step responses match ground truth |
| **Phase 2** — Write Gateway v1 | Implementation per ADR 012: `off`, `advisory`, `dry_run`, `confirm`, then `supervised`. First write protocol: OPC UA. Write policy schema and GUI editor. Proposal queue in the console. Roles and login | All 12 gateway scenarios pass against the Phase 1a DCS simulator. e2e shows proposal → confirm → write → read-back → audit entry; kill switch stops in one cycle. Gateway, policy and permissions pass review |
| **Phase 3** — Module 1 as a complete product (first release) | Online monitoring of all catalogue loops. Tuning path from detection to write after confirmation, KPI check, one-click rollback. Optional step-test assistant | Full cycle on the DCS simulator: weak loop detected → test → tuning → write after confirmation → KPI improvement → rollback works. Then a pilot at the owner's site in `confirm` mode |
| **Phase 4a** — Universal virtual-sensor engine with presets | See section 4.2 | A lab-and-analyser configuration built entirely in the GUI reproduces the exp31 numbers. exp30 (synthetic) still meets its criteria. Blind test on the next data delivery. Every v1 preset, configured only in the GUI, passes its L5 row against RougherSim, including the instrument-failure scenario (failover and accuracy criteria frozen in the protocol before the run) |
| **Phase 4b** — Asset templates and predictive maintenance | See section 4.3 (asset templates, expected-value models, health index, time to limit). Builds on the preset machinery of Phase 4a and the event management of Phase 3 | Every v1 asset template detects its injected degradation in RougherSim with the lead time and false-event rate set in a frozen protocol, and raises no event on operating-mode changes. Asset view in the GUI ranked by criticality |
| **Phase 5** — Connectors | PI (PI Web API, optionally AF SDK); SQL/ODBC profiles (IP.21, PHD, AVEVA/Wonderware Historian, WinCC); OPC DA/HDA through a wrapper or proxy UA; Excel and Parquet | Each connector covers history, live read and metadata. Each has a test on a recorded fixture. Real-source tests are owner tasks. Writes stay gateway-only |
| **Phase 6** — Fuzzy closed loop | Strategy Canvas (section 4.4). Supervisor advice becomes setpoint write proposals through the gateway: `confirm` first, then `supervised` | Write proposals flow through the gateway; run in `confirm` then `supervised` tested against the DCS simulator |
| **Phase 7** — MPC | Identification from step tests and an editable model matrix in the GUI. Linear MPC with constraints (QP) checked on `sim/`. C++ runtime per ADR 001 | MPC writes setpoints through the gateway in `supervised` mode against the DCS simulator |
| **Phase 8** — ML and optimisation | Operating-range recommendation and an economic layer (RTO) above MPC and fuzzy | Plan accepted by the owner. Economic objective and limits supplied by the owner |

## 8. Evidence discipline and claim limits

- Frozen protocols: an experiment freezes and commits its protocol before any run. Test seeds run once. Misses ship visibly; thresholds are not moved.
- Experiments serve the product features in this document. They are not a separate line of work.
- Simulator success is not a plant claim. Findings say "in our simulator, with our operator model".
- Real plant data stays outside the repository.

See `docs/TESTING_STRATEGY.md` (L0–L7 ladder), `docs/ASSUMPTIONS.md` (unproven assumptions and retirement plans), `experiments/README.md` (experiment index and status).

## 9. Anti-drift rule

Enforced for every task, and written into the repository `CLAUDE.md` in Phase 0:

1. Every task names the module and phase in this document.
2. Work on plant data yields a generic engine feature plus an example configuration, or nothing.
3. A new top-level element (package, experiment line, tool) requires the owner's approval.

## 10. Open owner decisions

| # | Decision | Blocks |
|---|---|---|
| 1 | First pilot DCS (ABB or Siemens) for PID-parameter writes and CAS conventions | Phase 3 pilot |
| 2 | Whether the step-test assistant may propose OUT writes in manual (`confirm` mode) | Phase 3 exit criteria |
| 3 | Licence of the separate DCS simulator project RougherSim (name decided); whether Siemens PLCSIM Advanced (trial) is the second check | Phase 1a |
| 4 | Whether there is legal access to ABB SoftController (Compact Control Builder) to check the ABB profile on a real stack | Phase 1a ABB verification |
| 5 | ADR 008 licence (AGPL-3.0-only) review | Release terms |
| 6 | Blind worklist review (≈20 loops) | Module 1 evidence |
| 7 | One real valve stroke test | Module 1 evidence |
| 8 | Optimisation objective (economic value per PV unit, operating limits) | Phase 8 |
| 9 | Write authority model: who may enable `confirm`/`supervised`, who may change policy, what the operator can always do | Phase 2 `supervised` |
| 10 | Virtual-sensor v1 preset set (section 4.2) and whether `backup` mode is in v1; which plant instruments (belt scale, pump, valve) can supply validation data | Phase 4a scope |
| 11 | Critical-asset list and v1 asset templates (section 4.3); whether maintenance history (work orders, failure records) can be shared for labelled events | Phase 4b evidence |

Also still relevant from PROJECT_DESIGN §8: real level step test (integrating loop), anomaly real data (≥ 2 weeks quiet plus labelled events), soft-sensor real data (lab timestamps, delay, tags), lab-stamp and missing-value-code meaning, analyser latency, UaExpert check and one ABB `PidCC` TI/TD export, ramp-warning precision against real archive gaps, next data delivery kept untouched for a blind exp31 test.

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
| `docs/adr/008` | AGPL-3.0-only licensing |
| `docs/adr/009` | Configuration is data (proposed) |
| `docs/adr/010` | Advisory supervisor, no writes (proposed; write position superseded by ADR 012) |
| `docs/adr/011` | Write path design; safety rules still in force |
| `docs/adr/012` | Writes are a product capability |
| `experiments/README.md` | Experiment index and status (closed lines stay in place) |
| `docs/archive/` | One-off plans and documents |
| `docs/PROJECT_DESIGN.md` | Historical record only; not maintained |