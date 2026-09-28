@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul || (echo [ERROR] Python is not installed. Install Python 3.11+ from python.org first. & pause & exit /b 1)
if not exist .venv py -3 -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m playwright install chromium
if not exist .env (copy .env.example .env >nul & echo [INFO] .env created. Open it with Notepad and fill in IDs/passwords.)
".venv\Scripts\python.exe" -m review_bot schedule install
pause
