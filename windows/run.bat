@echo off
setlocal

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Environment not found. Run windows\setup.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m bsense_experiment --short
if errorlevel 1 pause

