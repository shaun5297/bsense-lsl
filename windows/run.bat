@echo off
setlocal

cd /d "%~dp0\.."
set "VENV=.venv"

if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] Environment not found. Run windows\setup.bat first.
  pause
  exit /b 1
)

"%VENV%\Scripts\python.exe" -m bsense_experiment --short
if errorlevel 1 pause
