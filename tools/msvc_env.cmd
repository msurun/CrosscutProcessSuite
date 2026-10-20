@echo off
rem Loads the MSVC x64 build environment (cl, link) into the current cmd session.
rem Finds Visual Studio through vswhere, so no machine-specific path is hard-coded.
set "VS_INSTALLER=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer"
if not exist "%VS_INSTALLER%\vswhere.exe" (
  echo vswhere.exe not found: install Visual Studio Build Tools with the C++ workload. 1>&2
  exit /b 1
)
set "PATH=%VS_INSTALLER%;%PATH%"
set "VS_ROOT="
for /f "usebackq delims=" %%i in (`vswhere.exe -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS_ROOT=%%i"
if not defined VS_ROOT (
  echo No Visual Studio installation with the C++ build tools was found. 1>&2
  exit /b 1
)
call "%VS_ROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul
