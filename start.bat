@echo off
REM LawPrep - Windows launcher
REM Creates a venv on first run, installs requirements, starts the portal.

cd /d "%~dp0"

echo ============================================
echo   MH-CET Law 2027 - LawPrep Portal
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo Error: python not found. Install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Checking dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if not exist .env (
    echo.
    echo Note: no .env file found. AI/TTS features will be disabled.
    echo To enable them, copy .env.example to .env and add your API keys.
    echo.
)

echo.
echo Starting portal at http://127.0.0.1:5050
echo Press Ctrl+C to stop.
echo.
python app\app.py
