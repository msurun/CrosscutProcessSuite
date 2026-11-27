# Crosscut core (C++20)

Runtime core of the Crosscut Process Suite: `crosscut::Fopdt` and the pure two-layer MPC cycle.
CMake builds the C++20 library, GoogleTest tests and pybind11 bindings for Windows and Linux.

## Build and test

```bash
cmake -S core -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure

# Python/C++ parity test (the module lands in build/ or build/Release/)
CROSSCUT_CORE_MODULE_DIR=build python -m pytest core/tests
```

Options: `-DCROSSCUT_BUILD_TESTS=OFF`, `-DCROSSCUT_BUILD_PYTHON=OFF`, `-DCROSSCUT_SANITIZE=ON`
(AddressSanitizer + UndefinedBehaviorSanitizer on GCC/Clang, used for the C++ tests in CI).
Warnings are errors for the library (`/W4 /WX` on MSVC, `-Wall -Wextra -Wpedantic -Werror` elsewhere).
GoogleTest and pybind11 are fetched by CMake (network access needed on the first configure).

## MPC plain-data binding

`crosscut_core.mpc_cycle(controller, state, inputs)` returns `(result, next_state)` dictionaries.
The arguments have the same nested fields as `dataclasses.asdict` applied to the Python
`Controller`, `ControllerState` and `CycleInputs`. Numeric fields accept lists or NumPy arrays.
`mpc_initialise(controller, inputs)` creates the initial state; its first cycle holds the actual
MVs. Carry the returned state to the next call and supply actual MV read-back, including when
the gateway refused the previous proposal. The binding does not import the Python engine.

Results include absolute `moves`, time-major `move_plan` increments and `predicted_cvs`,
`steady_mvs`, `target_cvs`, `bias`, `active_constraints`, `relaxed_cvs`, `status`, `reason`,
`iterations` and measured `solve_time_s`. Status strings are `initialised`, `solved`, `relaxed`,
`hold` and latched `shed`, matching the reference. Invalid shapes or nonfinite inputs raise
`ValueError`; a numerical failure returns a held plan and never licenses CV relaxation.

The QP algorithm, deterministic stopping rules and scope are recorded in
[ADR 001 MPC addendum](../docs/adr/001-mpc-dense-qp.md). No new solver dependency is required.
