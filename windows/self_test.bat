@echo off
setlocal

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Environment not found. Run windows\setup.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m bsense_experiment --self-test
".venv\Scripts\python.exe" -m unittest discover -s tests -v
pause

