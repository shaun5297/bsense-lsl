@echo off
setlocal

cd /d "%~dp0\.."

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher was not found.
  echo Install Python 3.11 x64 from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv ".venv"
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m bsense_experiment --self-test
if errorlevel 1 goto :failed

echo.
echo [OK] Environment is ready.
pause
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Review the messages above.
pause
exit /b 1

