# ADR 001: C++20 runtime, Python offline tooling

Status: accepted (2026-10-10)

## Context
The suite has two kinds of code. The control runtime (cycle, MPC, write gateway, connectors that write to a DCS)
must be deterministic, run for weeks without restarts, ship as a single binary on Windows and Linux and be hard
to tamper with. The offline tooling (simulators, identification, ML training, experiments) needs the Python
numerical ecosystem and fast iteration.

## Decision
- The runtime core is written in C++20 and built with CMake (MSVC on Windows, GCC/Clang on Linux).
- Offline tooling is written in Python.
- Both sides share code through pybind11 bindings of the core, so simulations and backtests run the same
  controller code as production. The contract between them is the artifact format (`schemas/`).
- Until the first write to a real DCS, read-only products may stay in Python.

## Consequences
- Every core class needs a parity test against its Python reference (see `core/tests/test_python_parity.py`).
- C++ quality gates: warnings as errors, sanitizers in CI, unit tests, small well-tested core.
- Alternatives considered: Rust (memory safety, steeper learning curve), C#/.NET (good OPC UA stack, weaker
  protection of the code), Python only (prototype only).
