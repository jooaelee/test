@echo off
title Stop Warehouse Demand Forecast
cd /d "%~dp0"

echo Stopping the program (port 8501)...
echo.

set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>nul
    set FOUND=1
)

if "%FOUND%"=="1" (
    echo Stopped.
) else (
    echo Nothing appears to be running on port 8501.
)

echo.
pause
