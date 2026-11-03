@echo off
rem Keeps the API running: if it stops for any reason it starts again after 5 seconds.
rem Output goes to backend\data\api.log so the reason for a stop can be read later.
title Audit API (auto-restart)
cd /d "%~dp0backend"
:loop
echo [%date% %time%] API starting>> data\api.log
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8800 >> data\api.log 2>&1
echo [%date% %time%] API stopped (exit code %errorlevel%), restarting in 5 s>> data\api.log
timeout /t 5 /nobreak >nul
goto loop
