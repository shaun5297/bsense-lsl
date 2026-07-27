@echo off
setlocal EnableExtensions

cd /d "%~dp0\.."
if errorlevel 1 goto :failed

set "VENV=.venv"
set "PYTHON_MODE="
set "PYTHON_VERSION="
set "PYTHON_COMMAND="
set "PYTHON_EXE="

rem Reuse a valid environment. Move an invalid or cross-platform copy aside.
if not exist "%VENV%" goto :prepare_venv
if not exist "%VENV%\Scripts\python.exe" goto :backup_existing_venv
call :check_python "%VENV%\Scripts\python.exe"
if not errorlevel 1 goto :venv_ready
echo [INFO] Existing %VENV% is not a usable Python 3.11-3.13 Tk environment.

:backup_existing_venv
call :backup_venv
if errorlevel 1 goto :failed

:prepare_venv
call :find_python
if errorlevel 1 goto :no_python
call :create_venv
if errorlevel 1 goto :failed

:venv_ready
call :check_python "%VENV%\Scripts\python.exe"
if errorlevel 1 goto :invalid_venv

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

"%VENV%\Scripts\python.exe" -m pip uninstall -y bsense-lsl-experiment >nul 2>nul

"%VENV%\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

"%VENV%\Scripts\python.exe" -m bsense_experiment --self-test
if errorlevel 1 goto :failed

echo.
echo [OK] Python 3.11-3.13 environment is ready: %VENV%
call :wait_if_interactive
exit /b 0

:backup_venv
if not exist "%VENV%" exit /b 0
set "VENV_BACKUP=.venv.bak.%RANDOM%%RANDOM%"
echo [INFO] Moving invalid %VENV% to %VENV_BACKUP%.
ren "%VENV%" "%VENV_BACKUP%"
if errorlevel 1 exit /b 1
exit /b 0

:find_python
where py >nul 2>nul
if errorlevel 1 goto :find_path_commands
call :try_py 3.13
if defined PYTHON_MODE exit /b 0
call :try_py 3.12
if defined PYTHON_MODE exit /b 0
call :try_py 3.11
if defined PYTHON_MODE exit /b 0

:find_path_commands
call :try_command python3.13
if defined PYTHON_MODE exit /b 0
call :try_command python3.12
if defined PYTHON_MODE exit /b 0
call :try_command python3.11
if defined PYTHON_MODE exit /b 0
call :try_command python
if defined PYTHON_MODE exit /b 0

call :try_exe "%LocalAppData%\Programs\Python\Python313\python.exe"
if defined PYTHON_MODE exit /b 0
call :try_exe "%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PYTHON_MODE exit /b 0
call :try_exe "%LocalAppData%\Programs\Python\Python311\python.exe"
if defined PYTHON_MODE exit /b 0
exit /b 1

:try_py
py -%~1 -c "import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_MODE=py"
set "PYTHON_VERSION=%~1"
exit /b 0

:try_command
where %~1 >nul 2>nul
if errorlevel 1 exit /b 0
%~1 -c "import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_MODE=command"
set "PYTHON_COMMAND=%~1"
exit /b 0

:try_exe
if not exist "%~1" exit /b 0
call :check_python "%~1"
if errorlevel 1 exit /b 0
set "PYTHON_MODE=exe"
set "PYTHON_EXE=%~1"
exit /b 0

:create_venv
if /i "%PYTHON_MODE%"=="py" goto :create_venv_with_py
if /i "%PYTHON_MODE%"=="command" goto :create_venv_with_command
if /i "%PYTHON_MODE%"=="exe" goto :create_venv_with_exe
exit /b 1

:create_venv_with_py
py -%PYTHON_VERSION% -m venv "%VENV%"
exit /b %ERRORLEVEL%

:create_venv_with_command
%PYTHON_COMMAND% -m venv "%VENV%"
exit /b %ERRORLEVEL%

:create_venv_with_exe
"%PYTHON_EXE%" -m venv "%VENV%"
exit /b %ERRORLEVEL%

:check_python
"%~1" -c "import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>nul
exit /b %ERRORLEVEL%

:invalid_venv
echo [ERROR] %VENV% is not a valid Python 3.11-3.13 Tk environment.
goto :failed

:no_python
echo.
echo [ERROR] No installed Python 3.11-3.13 with Tk was found.
echo This script does not download or install Python automatically.
echo Install Python 3.13 x64 from:
echo https://www.python.org/downloads/windows/
echo Select the py launcher and Tcl/Tk options, then run this script again.
call :wait_if_interactive
exit /b 1

:failed
echo.
echo [ERROR] Setup failed. Review the messages above.
call :wait_if_interactive
exit /b 1

:wait_if_interactive
if defined CI exit /b 0
if defined BSENSE_NONINTERACTIVE exit /b 0
pause
exit /b 0
