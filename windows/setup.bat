@echo off
setlocal

cd /d "%~dp0\.."
set "VENV=.venv"
set "PYTHON_VERSION=3.13"

if exist "%VENV%\pyvenv.cfg" if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] %VENV% was created on another operating system or is incomplete.
  echo Virtual environments cannot be copied between macOS and Windows.
  echo Rename or remove only %VENV%, then run windows\setup.bat again.
  goto :failed
)

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher was not found.
  echo Install Python 3.13 x64 from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  py -%PYTHON_VERSION% -m venv "%VENV%"
  if errorlevel 1 goto :failed
)

"%VENV%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)"
if errorlevel 1 (
  echo [ERROR] %VENV% is not a valid Python 3.13 Windows environment.
  echo Rename or remove only %VENV%, then run windows\setup.bat again.
  goto :failed
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

"%VENV%\Scripts\python.exe" -m pip uninstall -y bsense-lsl-experiment >nul 2>nul

"%VENV%\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

"%VENV%\Scripts\python.exe" -m bsense_experiment --self-test
if errorlevel 1 goto :failed

echo.
echo [OK] Python 3.13 environment is ready: %VENV%
pause
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Review the messages above.
pause
exit /b 1
