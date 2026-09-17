@echo off
REM Lord of the Clipboard — launcher. Double-click me.
REM Uses paths relative to this file so it runs from anywhere (USB, synced folder...).
cd /d "%~dp0"

REM First run: create a local virtual env and install dependencies.
if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating virtual environment...
    py -3 -m venv .venv || python -m venv .venv
    call ".venv\Scripts\activate.bat"
    echo [setup] installing dependencies...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

REM Run without a console window on subsequent launches via pythonw if present.
start "" ".venv\Scripts\pythonw.exe" -m src.app
