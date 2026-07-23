@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Error: .venv not found. Run windows\setup.bat first.
  exit /b 1
)

".venv\Scripts\python.exe" -c "import platform,sys; sys.exit(0 if platform.machine().lower() in ('amd64','x86_64') else 1)"
if errorlevel 1 (
  echo Error: Windows release must be built in an x64 environment.
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -e ".[release]"
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" "tools\build_release.py" %*
exit /b %errorlevel%
