# Crosscut Process Suite

Process performance suite for mineral processing. **Status: early development. Module 1 (loop monitoring and PID tuning) is usable as an advisory tool and is validated on simulated loops; only parts of the triage were checked on public real-loop data, and nothing has been tested on a plant.**

The goal is a toolkit that a process engineer can configure without programming:

- loop monitoring and PID tuning,
- soft sensors and anomaly detection,
- model predictive control and fuzzy / expert rules,
- ML-based recommendation of operating ranges and economic optimization,
- native OPC UA connectivity.

Every module is optional; a plant picks what it needs.

## Module 1: loop monitoring and PID tuning

What a process engineer can do today, on simulator data or on a CSV / SQL export (details, evidence and limits per
item: [docs/HANDOFF.md](docs/HANDOFF.md)):

- **Loop overview and worklist** (web UI `frontend/`, API `api/`, logic `loops/`): health in %, findings (manual,
  saturated, flatline, oscillating, poor performance, valve hints), key numbers, trends, and per loop a **next action
  and a priority rank**. The ranking is a rule, not a validated score. Conclusions that need per-loop knowledge
  (output range, dead time, oscillation limits) are reported as "not assessed" instead of being guessed.
- **Oscillation without configuration**: a parameter-free ACF regularity test (Thornhill et al. 2003 with our noise
  band). It misses records with fewer than about eight cycles and can raise false alarms on fast noise in long records
  (up to 9 % in simulation); the finding says so.
- **Valve**: travel, reversals, output resolution and sizing hints; a **weak stiction hint** from passive data (never a
  diagnosis) and a **guided valve stroke test** that gives deadband and resolution from a deliberate test
  ([docs/VALVE_STROKE_TEST.md](docs/VALVE_STROKE_TEST.md); validated on simulation only).
- **Tuning report**: FOPDT model from a step test, SIMC and AMIGO PI/PID settings, conversion to vendor forms
  (Siemens checked against public manuals, ABB partly), withheld when the model fits badly. **Tuning from history**
  uses natural setpoint steps; on real data it rarely applies and then says "do a bump test".
- **Benefit estimate** with its assumptions next to the number.
- **Fuzzy Studio** (advisory rule bases with what-if and replay) and **live OPC UA demos**:
  [docs/LIVE_DEMO.md](docs/LIVE_DEMO.md).

Limits you should know: all data in this repository is synthetic and all validation is simulated, apart from
exploratory runs on two public loop datasets (SACAC, ISDB; not redistributed). Stiction cannot be diagnosed from
passive data, time-constant and delay estimates are poor at full noise, the sluggish-loop (idle index) idea was tried
and dropped, and the OPC UA server was tested with a Python client only. Tuning and advice are advisory: nothing in
this repository writes to a DCS.

## Module 2: advisory supervisor

Status: proposed design ([ADR 010](docs/adr/010-advisory-supervisor.md)), tested on simulated data only.

- **What it is**: advice on the mill feed setpoint (increase, decrease or hold) from a fuzzy rule base. Advice is gated by
  module 1 loop state (manual, saturated and flatline block; oscillating only warns), explained by its dominant rules,
  and written to an append-only, hash-chained log. An operator records a decision (accepted, rejected or deferred) with
  a reason code.
- **No writes to a plant**: the package never imports OPC UA or connector code and writes only under `_advisory/` and
  `_supervisor/` in the data root. Mode can only be `off` or `advisory`; a closed-loop mode needs a future ADR.
- **Where**: `supervisor/` (package `crosscut_supervisor`), `api/src/crosscut_api/supervisor_routes.py`, the Advisor view
  in `frontend/` (`src/advisory.ts`, `src/components/AckForm.tsx`), and the schemas `schemas/supervisor.schema.json`
  and `schemas/advisory-record.schema.json`.
- **Try it**: in the Advisor view, load the bundled example `supervisor/examples/mill_feed_advisor.json`, then run a
  replay on a simulated dataset. Advice shows its gate state; during injected manual or flatline windows no magnitude
  is given.
- **Claim limits**:
  - Evidence is simulation only. In exp27 (20 test seeds, one run, frozen criteria) the fuzzy v2 rule base kept P80 on
    target more often than a crisp threshold rule (median 0.65 vs 0.49) without more mill-power excursions. A scripted
    operator that uses the ore hardness estimate reached 0.79, so the advisor does not replace that information.
    The crisp baseline was not tuned, and the rule bases were shaped on this simulator
    ([results](experiments/exp27_supervisor_benefit/README.md)).
  - Acceptance of advice (0.8) and the 300 s delay are assumptions of the simulated operator, not measurements.
  - No plant data has been used.
  - `who` on an acknowledgement is free text and is not authenticated.

## Foundations (stage 0)

- Simulators with known ground truth: Wood-Berry distillation column and a grinding circuit (HPGR, mill, cyclone)
  with an operator that confounds setpoints with ore hardness (`sim/`).
- Reproducible Parquet datasets, named scenarios, `python -m crosscut_sim.run` (`sim/`).
- OPC UA test server (client writes, heartbeat watchdog) and a collector (`opcua/`).
- Artifact manifests with integrity checks (`artifacts/`), JSON Schema data contracts (`schemas/`).
- C++20 core smoke test with a pybind11 parity test, CI on Linux and Windows (`core/`).
- [Experiment 0](experiments/exp00_sp_vs_mv/README.md): which signals recover true gains from confounded
  closed-loop data. Short answer: raw setpoint and actuator signals fail, high-passed ones recover the gain.

![Experiment 0](experiments/exp00_sp_vs_mv/results/gains.png)

## Quick start

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python -m crosscut_sim.run --plant mill_circuit --scenario observational --duration 6h --out data/
python -m crosscut_opcua.server --plant wood_berry --scenario nominal --port 4840 --speed 10
python experiments/exp00_sp_vs_mv/exp00.py --seeds 5 --hours 48
```

## Repository layout

| Path | Content |
|---|---|
| `schemas/` | JSON Schemas for the data contracts (single source of truth) |
| `sim/` | Plant simulators with known ground truth (`crosscut-sim`) |
| `opcua/` | OPC UA test server and data collector |
| `artifacts/` | Artifact manifests (read, write, verify) |
| `core/` | C++20 runtime core with Python bindings |
| `loops/` | Loop monitoring, KPIs and worklist, valve tests, identification, tuning, benefit |
| `api/` | FastAPI backend of the web UI |
| `frontend/` | Web UI (React, TypeScript) |
| `connectors/` | CSV, SQL and OPC UA import |
| `fuzzy/` | Fuzzy rule bases and inference |
| `ident/` | Model identification and ML tooling (planned) |
| `experiments/` | Reproducible experiments |
| `docs/` | Documentation, architecture decision records, provenance log |

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Code, comments, commit messages and documentation are written in English.

## Provenance

All methods are implemented from public literature; see [docs/PROVENANCE.md](docs/PROVENANCE.md).
All data in this repository is synthetic.

## License

GNU Affero General Public License v3.0 (AGPL-3.0-only), see [LICENSE](LICENSE). A commercial licence is available
for users who cannot work under the AGPL; see [LICENSING.md](LICENSING.md). Your own configuration, rules and
models are data and stay yours ([ADR 009](docs/adr/009-configuration-versus-code.md)).
