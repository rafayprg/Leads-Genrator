@echo off
rem Try the dashboard with made-up data: separate demo.db and a fake Apify, nothing is spent.
cd /d "%~dp0backend"
start "Audit API (demo)" .venv\Scripts\python scripts\demo_server.py
cd /d "%~dp0frontend"
start "Audit dashboard" cmd /c npm run dev
ping -n 4 127.0.0.1 >nul
start "" http://localhost:5190
