@echo off
rem Windows wrapper for the Crosscut data API (uvicorn, 127.0.0.1:8000).
rem Root: %CROSSCUT_ROOT% if set, else C:\crosscut\data. Restarts after any exit.
if "%CROSSCUT_ROOT%"=="" set "CROSSCUT_ROOT=C:\crosscut\data"
set "PY=C:\crosscut\.venv\Scripts\python.exe"
:loop
"%PY%" -c "import os; from pathlib import Path; import uvicorn; from crosscut_api.app import create_app; uvicorn.run(create_app(Path(os.environ['CROSSCUT_ROOT'])), host='127.0.0.1', port=8000)"
echo [run-api] exited with code %ERRORLEVEL%, restarting in 5 s
timeout /t 5 /nobreak >nul
goto loop
