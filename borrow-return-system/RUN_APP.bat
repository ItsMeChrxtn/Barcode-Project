@echo off
setlocal EnableExtensions
title Borrow-Return System

cd /d "%~dp0"

echo [INFO] This script is for Windows only.
echo [INFO] For Raspberry Pi 5, run: ./RUN_APP_PI.sh
echo.

set "APP_URL=http://127.0.0.1:5000"
set "VENV_PYTHON=.venv\Scripts\python.exe"

echo Starting Borrow-Return System...
echo.

if not exist "%VENV_PYTHON%" (
    echo Creating virtual environment...

    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if %errorlevel%==0 (
            python -m venv .venv
        ) else (
            echo [ERROR] Python is not installed or not available in PATH.
            echo Install Python 3, then run this file again.
            pause
            exit /b 1
        )
    )
)

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo Installing dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip
"%VENV_PYTHON%" -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo requirements.txt install failed. Retrying with compatible Pillow package...
    "%VENV_PYTHON%" -m pip install Flask==3.1.0 Werkzeug==3.1.3 python-barcode==0.15.1 gunicorn==23.0.0 flask-cors==5.0.1 ntplib==0.4.0 Pillow
    if %errorlevel% neq 0 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
)

echo Initializing database schema...
"%VENV_PYTHON%" init_db.py
if %errorlevel% neq 0 (
    echo [ERROR] Failed to initialize database.
    pause
    exit /b 1
)

if not exist "database.db" (
    echo Seeding sample data for first run...
    "%VENV_PYTHON%" seed_data.py
)

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"

echo.
echo App is running at %APP_URL%
echo Press Ctrl+C to stop.
echo.
"%VENV_PYTHON%" app.py

pause
