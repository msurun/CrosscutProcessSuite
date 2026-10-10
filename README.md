# Crosscut Process Suite

Process performance suite for mineral processing. **Status: early development, nothing is usable yet.**

The goal is a toolkit that a process engineer can configure without programming:

- loop monitoring and PID tuning,
- soft sensors and anomaly detection,
- model predictive control and fuzzy / expert rules,
- ML-based recommendation of operating ranges and economic optimization,
- native OPC UA connectivity.

Every module is optional; a plant picks what it needs.

## Repository layout (planned)

| Path | Content |
|---|---|
| `schemas/` | JSON Schemas for the data contracts (single source of truth) |
| `sim/` | Plant simulators with known ground truth (`crosscut-sim`) |
| `opcua/` | OPC UA test server and data collector |
| `core/` | C++20 runtime core with Python bindings |
| `ident/` | Model identification and ML tooling |
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

Apache License 2.0, see [LICENSE](LICENSE).
