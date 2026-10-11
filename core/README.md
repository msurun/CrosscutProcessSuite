# Crosscut core (C++20)

Runtime core of the Crosscut Process Suite. At this stage it only contains a smoke-test subset
(`crosscut::Fopdt`, a first-order lag with dead time) that proves the build pipeline:
CMake, GoogleTest, pybind11 and a parity test against the Python reference implementation.

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
