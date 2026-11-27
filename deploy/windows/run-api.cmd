@echo off
rem Windows wrapper for the Crosscut data API (uvicorn, 127.0.0.1:8000).
rem Root: %CROSSCUT_ROOT% if set, else C:\crosscut\data. Restarts after any exit.
if "%CROSSCUT_ROOT%"=="" set "CROSSCUT_ROOT=C:\crosscut\data"
set "PY=C:\crosscut\.venv\Scripts\python.exe"
:loop
"%PY%" -m crosscut_api --root "%CROSSCUT_ROOT%"
echo [run-api] exited with code %ERRORLEVEL%, restarting in 5 s
timeout /t 5 /nobreak >nul
goto loop
