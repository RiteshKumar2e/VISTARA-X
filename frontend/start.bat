@echo off
rem VISTARA-X frontend (Windows). First run installs the npm packages.
cd /d "%~dp0"
if not exist node_modules (
  call npm install || exit /b 1
)
if not exist .env if exist .env.example copy .env.example .env >nul
call npm run dev
