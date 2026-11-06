@echo off
rem Console / manual launcher for the Crosscut Write Gateway (no restart loop here).
rem Under NSSM, run python.exe directly instead (see install-gateway-service.md): NSSM does the
rem restarting and distinguishes exit code 2 (configuration error, do not restart).
rem Stop with Ctrl+C. The exit code of the gateway is passed on to the caller.
if "%CROSSCUT_ROOT%"=="" set "CROSSCUT_ROOT=C:\crosscut\data"
if "%CROSSCUT_POLICY%"=="" set "CROSSCUT_POLICY=%CROSSCUT_ROOT%\_gateway\policy\write-policy.json"
if "%CROSSCUT_PLANT_MAP%"=="" set "CROSSCUT_PLANT_MAP=%CROSSCUT_ROOT%\plant-map.json"
if "%CROSSCUT_MODE%"=="" set "CROSSCUT_MODE=advisory"
set "PY=C:\crosscut\.venv\Scripts\python.exe"
"%PY%" -m crosscut_gateway --root "%CROSSCUT_ROOT%" --policy "%CROSSCUT_POLICY%" --plant-map "%CROSSCUT_PLANT_MAP%" --mode "%CROSSCUT_MODE%"
exit /b %ERRORLEVEL%
