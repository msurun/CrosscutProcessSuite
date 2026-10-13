# Crosscut Process Suite

Process performance suite for mineral processing. **Status: early development, nothing is usable yet.**

The goal is a toolkit that a process engineer can configure without programming:

- loop monitoring and PID tuning,
- soft sensors and anomaly detection,
- model predictive control and fuzzy / expert rules,
- ML-based recommendation of operating ranges and economic optimization,
- native OPC UA connectivity.

Every module is optional; a plant picks what it needs.

## What exists today (stage 0)

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

GNU Affero General Public License v3.0 (AGPL-3.0-only), see [LICENSE](LICENSE).
