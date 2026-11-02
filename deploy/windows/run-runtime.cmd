@echo off
rem Windows wrapper for the Crosscut runtime. Restarts it after any exit.
rem Root: %CROSSCUT_ROOT% if set, else C:\crosscut\data. Stop with Ctrl+C.
if "%CROSSCUT_ROOT%"=="" set "CROSSCUT_ROOT=C:\crosscut\data"
set "PY=C:\crosscut\.venv\Scripts\python.exe"
:loop
"%PY%" -m crosscut_runtime --root "%CROSSCUT_ROOT%"
echo [run-runtime] exited with code %ERRORLEVEL%, restarting in 5 s
timeout /t 5 /nobreak >nul
goto loop
