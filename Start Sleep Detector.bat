@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo First time running? Running install.bat...
    call install.bat
)

call .venv\Scripts\activate.bat
python heart_rate_live.py --ble %*
pause
