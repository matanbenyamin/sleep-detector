@echo off
setlocal
cd /d "%~dp0"

echo ==========================================================
echo       Sleep Detector - Windows Automated Setup
echo ==========================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3 was not found in PATH.
    echo Please install Python 3 from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Creating Python virtual environment (.venv)...
if not exist .venv (
    python -m venv .venv
)

echo [2/3] Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] Done!
echo ==========================================================
echo Setup complete. Double-click "Start Sleep Detector.bat" to run.
echo ==========================================================
pause
