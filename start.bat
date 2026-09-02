@echo off
setlocal
cd /d "%~dp0"
title Quran Video Studio - Launcher

echo Starting Quran Video Studio...

REM Backend (FastAPI on :8000)
start "QVS Backend" /min cmd /c "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

REM Frontend (Vite on :5173)
start "QVS Frontend" /min cmd /c "cd /d %~dp0frontend && npm run dev"

REM wait for services then open browser
timeout /t 4 /nobreak >nul
start http://localhost:5173

echo.
echo  App:       http://localhost:5173
echo  Backend:   http://localhost:8000  (docs at /docs)
echo.
echo  Close the "QVS Backend" and "QVS Frontend" windows to stop.
pause
endlocal
