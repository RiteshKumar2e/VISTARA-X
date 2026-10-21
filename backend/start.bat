@echo off
rem VISTARA-X backend (Windows). First run creates .venv and installs the core packages.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || exit /b 1
  echo Optional extras (PyBullet, YOLOv8, Whisper^): .venv\Scripts\pip install -r requirements-optional.txt
)
if not exist .env if exist .env.example copy .env.example .env >nul
.venv\Scripts\python -m uvicorn app.main:app --port 8000
