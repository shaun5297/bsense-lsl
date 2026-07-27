@echo off
setlocal

cd /d "%~dp0\.."
set "VENV=.venv"

rem --- 来自其他系统或解释器版本不符的 venv：移开后重建 ---
if exist "%VENV%\pyvenv.cfg" if not exist "%VENV%\Scripts\python.exe" (
  echo [提示] %VENV% 来自其他系统或不完整，已移动并重新创建。
  ren "%VENV%" ".venv.bak.%RANDOM%%RANDOM%"
)
if exist "%VENV%\Scripts\python.exe" (
  "%VENV%\Scripts\python.exe" -c "import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo [提示] %VENV% 不是有效的 Python 3.11-3.13 Tk 环境，已移动并重新创建。
    ren "%VENV%" ".venv.bak.%RANDOM%%RANDOM%"
  )
)

rem --- 查找带 Tk 的 Python 3.13，本脚本不自动下载安装 ---
set "PYTHON_EXE="
call :find_python
if not defined PYTHON_EXE goto :no_python

if not exist "%VENV%\Scripts\python.exe" (
  "%PYTHON_EXE%" -m venv "%VENV%"
  if errorlevel 1 goto :failed
)

"%VENV%\Scripts\python.exe" -c "import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] %VENV% 创建失败或不是有效的 Python 3.11-3.13 Tk 环境。
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
echo [OK] Python 3.11-3.13 environment is ready: %VENV%
pause
exit /b 0

:find_python
set "PYTHON_EXE="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    if not defined PYTHON_EXE (
      py -%%V -c "import sys, tkinter" >nul 2>nul
      if not errorlevel 1 (
        for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)"') do set "PYTHON_EXE=%%P"
      )
    )
  )
)
if defined PYTHON_EXE exit /b 0
for %%D in (Python313 Python312 Python311) do (
  if not defined PYTHON_EXE (
    if exist "%LocalAppData%\Programs\Python\%%D\python.exe" (
      "%LocalAppData%\Programs\Python\%%D\python.exe" -c "import sys, tkinter" >nul 2>nul
      if not errorlevel 1 set "PYTHON_EXE=%LocalAppData%\Programs\Python\%%D\python.exe"
    )
  )
)
exit /b 0

:no_python
echo.
echo [ERROR] 未找到带 Tk 的 Python 3.11-3.13，本脚本不自动下载安装。
echo 请从 https://www.python.org/downloads/windows/ 安装 Python 3.13 x64
echo （安装时勾选 py launcher 与 tcl/tk），然后重新运行本脚本。
pause
exit /b 1

:failed
echo.
echo [ERROR] Setup failed. Review the messages above.
pause
exit /b 1
