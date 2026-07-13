@echo off
setlocal enabledelayedexpansion
title Warehouse Demand Forecast
cd /d "%~dp0"

echo ============================================
echo   Warehouse Demand Forecast - Starting
echo ============================================
echo.

REM ---- 1) Check Python is really installed (not the Microsoft Store stub) --
python --version >nul 2>nul
if errorlevel 1 goto :no_python

set "PYVER_TAG="
for /f "tokens=1" %%a in ('python --version 2^>^&1') do set "PYVER_TAG=%%a"
if /i not "%PYVER_TAG%"=="Python" goto :no_python

REM ---- 2) First run only: create venv and install requirements --------------
if exist ".venv\Scripts\python.exe" goto :run_app

echo First time setup - installing required packages.
echo This can take a few minutes, please wait...
echo.
python -m venv .venv
if errorlevel 1 goto :venv_failed

echo Installing libraries...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed

echo.
echo Setup complete.
echo.

:run_app
REM ---- 3) Skip Streamlit's one-time interactive "Email:" prompt -------------
REM Without this, the very first run on a machine can sit waiting for input
REM that never comes when launched with a hidden window (see Start.vbs).
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit" >nul 2>nul
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

REM ---- 4) Run: the browser will open automatically --------------------------
echo Starting the program. Your browser will open shortly...
echo (Keep this black window open while you use the program)
echo (To stop, close this window or press Ctrl+C, or use Stop.bat)
echo.

".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false

goto :end

:no_python
echo [ERROR] A working Python installation was not found.
echo.
echo This can also happen if Windows only has the Microsoft Store
echo "python.exe" placeholder installed, which does not work here.
echo.
echo To fix this:
echo   1. Go to https://www.python.org/downloads/
echo   2. Download and run the Windows installer
echo   3. On the first install screen, check the box
echo      "Add python.exe to PATH" before clicking Install
echo   4. If a Microsoft Store page opened when you typed "python" before,
echo      turn that off: Settings - Apps - Advanced app settings -
echo      App execution aliases - turn OFF "python.exe" and "python3.exe"
echo   5. Close this window and double-click Run.bat again
echo.
goto :end

:venv_failed
echo.
echo [ERROR] Could not create the Python virtual environment.
echo Please make sure Python was installed correctly from python.org
echo and that "Add python.exe to PATH" was checked during install.
goto :end

:pip_failed
echo.
echo [ERROR] Failed to install required libraries.
echo Please check your internet connection and try again.
goto :end

:end
echo.
pause
