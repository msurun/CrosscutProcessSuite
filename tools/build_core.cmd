@echo off
rem Builds and tests core/ (C++20) with MSVC and the repo's .venv Python, so the pybind11 module
rem matches the venv's Python version. Run from anywhere; the module lands in build\.
setlocal
set "ROOT=%~dp0.."
call "%~dp0msvc_env.cmd" || exit /b 1
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo %PY% not found: create the virtual environment first. 1>&2
  exit /b 1
)
cd /d "%ROOT%"
cmake -S core -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DPython_EXECUTABLE="%PY%" -DPython3_EXECUTABLE="%PY%" -DPYTHON_EXECUTABLE="%PY%" || exit /b 1
cmake --build build || exit /b 1
ctest --test-dir build --output-on-failure || exit /b 1
set "CROSSCUT_CORE_MODULE_DIR=build"
"%PY%" -m pytest core\tests -q
