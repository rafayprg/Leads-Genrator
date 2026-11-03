@echo off
cd /d "%~dp0backend"
.venv\Scripts\python -m alembic upgrade head
start "Audit API (auto-restart)" /min cmd /c "%~dp0run_api.bat"
cd /d "%~dp0frontend"
start "Audit dashboard" cmd /c npm run dev
ping -n 4 127.0.0.1 >nul
start "" http://localhost:5190
