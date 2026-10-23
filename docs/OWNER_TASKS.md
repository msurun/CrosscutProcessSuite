# Owner tasks

## What only the owner can do or decide

Each item lists why it matters and what to bring back. Tick a box when the item is done and the result is recorded in the repo.

### Reviews

- [ ] **Review ADR 008 (AGPL).**
  - Why: the licence decides what a customer may run and publish.
  - Bring back: accept, or a list of changes to the ADR.
- [ ] **Review ADR 010 (advisory supervisor).**
  - Why: it defines what the software may recommend and how operators acknowledge advice.
  - Bring back: accept, or a list of changes to the ADR.
- [ ] **Review ADR 011 (write path) when it exists.**
  - Why: it is the only place where a write to a live system would be allowed.
  - Bring back: accept, or a decision on each open point in the ADR.

### Flotation cell level step test

- [ ] **Record a level step test on the flotation cell.**
  - Why: the level loop model for the integrating-loop work (exp28) needs a real step response.
  - Needs:
    - PV level tag, OUT tag, mode, setpoint, units, sample period
    - the loop in manual, output moved as a single step or a doublet
    - at least 20 % quiet time before the first output move
    - several dead times after the last move
    - which valve and which cell
  - Format: CSV with columns `t_utc, tag, value, quality`, or a wide CSV with a header.
  - Bring back: the file, marked internal.

### Real valve stroke test

- [ ] **Run one real valve stroke test on a flow loop.**
  - Why: the simulator stroke model is unverified against a real valve.
  - Procedure: `docs/VALVE_STROKE_TEST.md`.
  - Bring back: the record and the filled results table.

### Blind review of the worklist

- [ ] **Ask an independent control engineer to review about 20 loops blind.**
  - Why: the worklist ranking has no outside check yet. The author is not independent.
  - Pass criteria: Kendall tau >= 0.5 and >= 80 % agreement on the next action.
  - Bring back: the reviewer's ranking and next-action choice for each loop.

### UaExpert check

- [ ] **Check the OPC UA demo with UaExpert.**
  - Why: confirms the live demo server behaves as an OPC UA client expects.
  - Procedure: `docs/LIVE_DEMO.md`.
  - Bring back: a note of what was browsed and any error text.

### ABB unit

- [ ] **Provide the TI/TD unit from one real PidCC loop export.**
  - Why: the ABB PID block time units are currently assumed, not checked.
  - Bring back: the export file (marked internal) and the TI and TD values as the controller shows them.

### Derived tables

- [ ] **Decide whether SACAC and ISDB providers may be asked about publishing derived tables.**
  - Why: the derived tables may contain data the providers own.
  - Bring back: a yes or no per provider, in writing.

### Real data per module

- [ ] **Anomaly detection (Module 3): at least 2 weeks of quiet operation plus labelled events.**
  - Why: the detector limits can only be checked against real quiet data.
  - Bring back: CSV with columns `t_utc, tag, value, quality`, plus a list of labelled events with start and end times. Mark internal.
- [ ] **Soft sensor (Module 4): lab results with timestamps, the sample-delay offset, and the process tags.**
  - Why: the quality variable is only real with lab timestamps and the delay.
  - Bring back: lab results CSV, the delay in minutes, and the process tag list. Mark internal.

### Strings

- [ ] **Read the machine-written Polish and Spanish UI strings natively.**
  - Why: the machine translations have not been checked by a native speaker.
  - Bring back: the list with corrections, or a note that they are acceptable.

### Decisions

- [ ] **Write authority model: who may allow a write, operator authority, watchdog.**
  - Why: ADR 011 cannot be finished without it.
  - Bring back: a written decision for each of the three parts.
- [ ] **Optimisation objective: economic value per PV unit and limits.**
  - Why: no optimisation module can be built without an objective.
  - Bring back: the value per PV unit, and the operating limits.
- [ ] **Whether the UI needs authentication.**
  - Why: it decides the deployment design and the security review scope.
  - Bring back: yes or no, and who should have access.
- [ ] **Whether the first customer needs MPC.**
  - Why: MPC has no write path yet, so it is ruled out for now.
  - Bring back: yes or no, with the customer's reason.

## What I need back for the new modules

- [ ] **Try the Anomalies view with your own tags.**
  - Needs: the tag ids and two weeks of quiet operation (CSV with columns `t_utc, tag, value, quality`).
  - Bring back: the tag list and what the view showed. Mark internal.
- [ ] **Try the Soft sensor view with a lab CSV.**
  - Needs: a lab CSV with columns `sample_time, value`, the process tags and the lab sample delay in minutes.
  - Bring back: the files (marked internal) and the delay used.
- [ ] **Native review of the Polish and Spanish texts of the new views** (Anomalies and Soft sensor).
  - Bring back: a list of corrections, or a note that the texts are acceptable.
- [ ] **Decide the open points of ADR 011 (write path).**
  - Why: the design stays a proposal until these are decided; nothing may write before that.
  - Bring back: a decision on each open point listed in `docs/adr/011-write-path.md`.
