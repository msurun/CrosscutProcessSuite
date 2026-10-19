# Crosscut Process Suite

Process performance suite for mineral processing. **Status: early development. Module 1 (loop monitoring and PID tuning) works on synthetic data only; nothing has been tested on a real plant.**

The goal is a toolkit that a process engineer can configure without programming:

- loop monitoring and PID tuning,
- soft sensors and anomaly detection,
- model predictive control and fuzzy / expert rules,
- ML-based recommendation of operating ranges and economic optimization,
- native OPC UA connectivity.

Every module is optional; a plant picks what it needs.

## Module 1: loop monitoring and PID tuning

What a process engineer can do today, on simulator data or on a CSV / SQL export:

- **Loop overview and detail** (web UI, `frontend/`, API in `api/`): health in %, findings (manual, saturated,
  flatline, oscillating, poor performance, stiction), key numbers, trends. A finding with a stretch of data behind it
  links to that stretch in the trend.
- **Stiction detection** (`loops/`): shape of the controller output (He et al. 2007 curve fitting). Finds a sticking
  valve with low noise from a 4 % band, and with full noise only from about 8 % (about 70 % of 20 runs there, none with an operator moving the loop); a square-wave load
  disturbance is a known false alarm. See `experiments/exp01_stiction_validation/`.
- **Tuning report**: FOPDT model from a step test, SIMC and AMIGO PI settings, conversion to vendor forms. The report
  is withheld when stiction is suspected or when the model fits the data badly (R squared below 0.5).
- **Proof in closed loop** (`experiments/exp03_retune/`): detuned mill-circuit loops retuned from a recorded step
  test improved their IAE by 70-93 % in 14 of 15 runs (5 seeds, 3 loops); the 15th was refused by the poor-fit guard.
  Identification accuracy by noise level: `experiments/exp02_identification_accuracy/`.
- **Benefit estimate** with its assumptions next to the number; the variability cut can come from a measured retune.
- **Fuzzy Studio** (advisory rule bases with what-if and replay) and **live OPC UA demos**:
  [docs/LIVE_DEMO.md](docs/LIVE_DEMO.md).

Limits you should know: all data is synthetic; the time-constant and delay estimates are poor at full noise (gain is
usable); only setpoint steps were tested; only open-loop step tests identify well; conversion to ABB and Siemens
parameter forms is not yet checked against vendor documents (assumption A7); the OPC UA server was tested with a
Python client only, not with UaExpert. Tuning is advisory: nothing in this repository writes to a DCS.

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
| `loops/` | Loop monitoring, stiction detection, identification, tuning, benefit |
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
